# Dictate — Recent History live-update fix (handoff)

**Repo:** `arcforgelabs/dictate` (`master`)
**Symptom (reported):** the Settings window's *Recent history* shows a stale snapshot (e.g. stuck at 3 entries), timestamps read "just now" on entries that are hours old, and dictations made while the window is open never appear — "lost chats."

**TL;DR — nothing is actually lost.** The daemon writes every successful dictation to `recent-history.json` correctly (`HistoryStore.append`, atomic write, keeps 20). The tray's native **Recent History** dialog reads that file directly and shows the full, correct list. The bug is entirely in the **web Settings window**: it loads history once and never updates, and it renders a frozen relative-time string. Three linked faults below; patches follow.

---

## Root cause

### A. The UI server is started detached from the running daemon
`ui_launcher.ensure_server_started()` and `__main__._maybe_start_ui_server()` both call `ui_server.serve()` **with no arguments**. That constructs a *fresh* `EventBroker` and a *fresh* `HistoryStore`, with no link to the live `Daemon`. The daemon's `status_callback` / `recording_callback` hooks and its `history_store` are never connected to that broker.

> The history *file path* happens to match (both default to `user_data_dir()/recent-history.json`), so data is shared on disk — but no events ever cross from the daemon to the UI server.

### B. Nothing ever publishes `history-changed`
The frontend only refetches history when it receives a `history-changed` SSE event:

```js
// ui/src/App.jsx — subscribe handler
else if (ev.type === "history-changed") ipc.getState().then((st) => st && setHistory(mapHistory(st)));
```

But `Daemon._handle_result()` calls `history_store.append(...)` and then emits **nothing** (the daemon has no broker reference). So after the initial `getState()` on mount, the list is a frozen snapshot. The same gap means **`recording` events aren't published either**, so the live "Listening" state in the web UI is stale too.

### C. Relative timestamps are frozen strings
`UiBackend.get_history()` formats `time` as a relative string ("just now", "22m ago") **server-side at fetch time**, and `App.jsx` stores that literal string in state. With no refetch and no recompute, "just now" stays "just now" indefinitely. `createdAt` is already sent to the client — the label should be derived from it on the client and re-rendered on a timer.

---

## The fix (3 parts)

1. **Wire the daemon to the UI server's broker + shared history store** (parts A/B) — so `recording` and `history-changed` events flow.
2. **Publish `history-changed` after each successful append** (part B).
3. **Compute the relative label client-side from `createdAt`, re-rendering on a timer** (part C).

A live, working reference of the target UX is in this project: `dictate-app/Dictate Settings.html` → **Recent history** (seeded entries age correctly; new dictations appear immediately as "just now" and tick over to "1m ago", etc.).

---

## Patches

### 1. `src/dictate/daemon.py` — add a history hook + fire it on append

```python
# __init__ signature — add one parameter alongside the existing callbacks:
        status_callback: Callable[[str | None], None] | None = None,
        recording_callback: Callable[[bool], None] | None = None,
        history_callback: Callable[[], None] | None = None,   # <-- new
        recorder: AudioRecorder | None = None,
    ):
        ...
        self.recording_callback = recording_callback
        self.history_callback = history_callback               # <-- new
```

```python
# in _handle_result(), where history is saved:
        try:
            self.history_store.append(result.text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  History save failed: {exc}", file=sys.stderr)
        else:
            self._notify_history_changed()                     # <-- new
```

```python
# new helper, next to _notify_recording():
    def _notify_history_changed(self) -> None:
        if self.history_callback is None:
            return
        try:
            self.history_callback()
        except Exception as exc:  # noqa: BLE001
            print(f"\r  History callback failed: {exc}", file=sys.stderr)
```

### 2. `src/dictate/ui_launcher.py` — start the server wired to the daemon

```python
def ensure_server_started(daemon: object | None = None) -> object:
    """Start the in-process ui_server once, bridged to the live daemon."""
    global _server_handle
    if _server_handle is not None:
        return _server_handle
    from dictate import ui_server

    broker = ui_server.EventBroker()
    backend = ui_server.UiBackend(
        history_store=getattr(daemon, "history_store", None),  # share the daemon's store
        broker=broker,
    )
    _server_handle = ui_server.serve(backend=backend, broker=broker)
    if daemon is not None:
        _wire_daemon_events(daemon, broker)
    return _server_handle


def _wire_daemon_events(daemon: object, broker: object) -> None:
    """Fan the daemon's callbacks out to the UI broker WITHOUT clobbering any
    callback the tray already installed (chain, don't replace)."""
    prev_status = getattr(daemon, "status_callback", None)
    prev_recording = getattr(daemon, "recording_callback", None)

    def on_status(message: str | None) -> None:
        if prev_status is not None:
            try:
                prev_status(message)
            except Exception:  # noqa: BLE001
                logger.exception("prior status callback failed")
        broker.publish("status", message=message)

    def on_recording(active: bool) -> None:
        if prev_recording is not None:
            try:
                prev_recording(active)
            except Exception:  # noqa: BLE001
                logger.exception("prior recording callback failed")
        broker.publish("recording", active=bool(active))

    daemon.status_callback = on_status
    daemon.recording_callback = on_recording
    daemon.history_callback = lambda: broker.publish("history-changed")
```

> Chaining matters: `TrayIcon.__init__` sets `daemon.status_callback = self._on_daemon_status` before Settings is ever opened. `ensure_server_started(daemon)` runs lazily on open, so `prev_status` captures the tray's callback and both keep working.

### 3. `src/dictate/__main__.py` — reuse the wiring in headless mode

```python
def _maybe_start_ui_server(daemon: object) -> object | None:
    if not os.environ.get("DICTATE_UI_SERVER"):
        return None
    try:
        from dictate import ui_launcher
        return ui_launcher.ensure_server_started(daemon)   # was: ui_server.serve()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Failed to start the UI control server")
        return None
```

### 4. `src/dictate/tray.py` — pass the daemon when opening Settings

```python
    def _on_open_settings(self, _item):
        from dictate import ui_launcher
        launched = ui_launcher.open_settings_window(
            start_server=lambda: ui_launcher.ensure_server_started(self.daemon),  # was: ui_launcher.ensure_server_started
        )
        ...
```

### 5. `ui/src/store.jsx` — client-side relative-time helper

```js
// Derive the label from a timestamp every render. Mirrors ui_server._relative.
export function formatHistoryTime(createdAt) {
  const t = typeof createdAt === "number" ? createdAt : Date.parse(createdAt);
  if (Number.isNaN(t)) return "";
  const d = new Date(t);
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  const clock = `${h}:${m} ${ap}`;
  const secs = Math.floor((Date.now() - t) / 1000);
  let rel;
  if (secs < 45) rel = "just now";
  else if (secs < 3600) rel = `${Math.max(1, Math.floor(secs / 60))}m ago`;
  else if (secs < 86400) rel = `${Math.floor(secs / 3600)}h ago`;
  else rel = `${Math.floor(secs / 86400)}d ago`;
  return `${clock} · ${rel}`;
}
```

### 6. `ui/src/App.jsx` — keep the raw timestamp, not the frozen string

```js
// map the engine's history payload — carry createdAt, drop the pre-rendered string
const mapHistory = (st) =>
  (st.history || []).map((h) => ({ id: h.id, text: h.text, createdAt: h.createdAt }));

// mock-mode demo append: store a real timestamp, match the engine's 20-entry cap
const pushHistory = (text) =>
  setHistory((h) => [{ id: "h" + Date.now(), createdAt: new Date().toISOString(), text }, ...h].slice(0, 20));
```

### 7. `ui/src/views.jsx` — render the live label + tick

```js
import { useStore, MODELS, modelById, formatHistoryTime } from "./store.jsx";

function HistoryView() {
  const s = useStore();
  // Re-render so "just now" → "2m ago" ages without a refetch.
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);
  ...
  // in the row, replace {it.time} with:
  <div className="t-mono" style={{ color: "var(--subtle)", fontSize: 10.5 }}>
    {formatHistoryTime(it.createdAt)}
  </div>
}
```

> `UiBackend.get_history()` already returns `createdAt` (ISO 8601). Its `time` field becomes unused by the client — leave it or drop it; harmless either way.

---

## Verification checklist

- [ ] Launch the app, open Settings → Recent history. Dictate something. **The new entry appears within ~1s** (no reopen).
- [ ] Leave Settings open ~2 min. A "just now" entry **ages to "1m ago", "2m ago"** on its own.
- [ ] Confirm the live **Listening** state in the Settings hero now reflects real recording (recording events flow through the same broker).
- [ ] Tray → Recent History (native dialog) and the web list **agree** (same shared store).
- [ ] Reopen Settings after several dictations: full recent list (up to 20) is present, none lost.

## Suggested tests (existing suites: `tests/`, `ui/src/test/`)
- `daemon`: a successful `_handle_result` calls `history_callback` exactly once; failure paths don't.
- `ui_launcher._wire_daemon_events`: chains an existing `status_callback`; sets `recording_callback` and `history_callback` that publish the right event types.
- `ui/src/test`: `formatHistoryTime` returns "just now" / "Nm ago" / "Nh ago" across thresholds; `App` re-renders the label on its interval.

## Notes / non-goals
- No schema or storage change — `recent-history.json` format is untouched; `MAX_ENTRIES = 20` unchanged.
- No new dependencies. The SSE broker (`EventBroker`) and `createdAt` field already exist; this just connects what's already there.
