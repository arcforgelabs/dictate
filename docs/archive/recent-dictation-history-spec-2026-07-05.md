# Recent Dictation History Recovery (Feature Scope)

Status: historical implementation spec. The recovery mechanism now surfaces in
the desktop UI as local dictation history / Notes rather than as the primary
product direction. Keep this file for implementation context; use
[TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md) for the current transcript-first
recording and meeting plan.

## Why this exists

Current dictation flow is:

1. User holds the configured push-to-talk shortcut to record.
2. User releases the shortcut.
3. Dictate transcribes and sends text to the active target (`xdotool`/`wtype`/`ydotool`).

If text is lost after that step (wrong target, accidental deletion, no editable field), there is no recovery path. This feature adds a lightweight local history so the most recent dictated text can be recovered and copied again.

## Product intent

Add a **recovery mechanism** for recent dictations:

1. Keep the last `3` successful dictations.
2. Expose them from tray utility via **Recent History...**.
3. Show a short preview list.
4. Clicking an item copies its full text to clipboard.
5. Existing dictation behavior stays unchanged.

## Scope (v1)

In scope:

1. Capture successful dictation text for daemon/tray usage.
2. Store a rolling history of last 3 entries.
3. Persist history to local file so recovery survives process restart/crash.
4. Add tray menu entry to open a GTK dialog showing recent items.
5. Copy selected history item to clipboard.
6. Add tests for history persistence logic and daemon integration path.

Out of scope:

1. Search/filter in history.
2. Export/import history.
3. Cross-device sync.
4. Encryption at rest.
5. Large history sizes beyond fixed small ring buffer.

## Required behavior

### 1) Capture rules

1. Capture only when `TranscriptionResult.status == "ok"` and `result.text` is non-empty.
2. Write history **before** text is sent to output backend.
3. If output backend fails, the captured text must still remain recoverable.
4. Do not capture `empty`, `too_short`, `no_speech`, or `error` statuses.

### 2) Retention rules

1. Keep exactly up to `3` most recent entries (newest first).
2. Preserve duplicate texts as separate events (same text spoken twice counts twice).
3. Truncate only by entry count, not by character length.

### 3) Persistence rules

1. Storage path: platform data directory (`~/.local/share/dictate/recent-history.json` on Linux, `%LOCALAPPDATA%\dictate\recent-history.json` on Windows).
2. File format: JSON with explicit version field and entry list.
3. Writes should be atomic (`tmp + replace`) to avoid partial corruption.
4. If file is missing/corrupt/unreadable, fallback to empty history without crashing.

Suggested JSON shape:

```json
{
  "version": 1,
  "entries": [
    {
      "id": "2026-02-25T17:04:11.123456+00:00",
      "created_at": "2026-02-25T17:04:11.123456+00:00",
      "text": "full dictated text"
    }
  ]
}
```

### 4) Tray UI rules

1. Add new tray menu item label: `Recent History...`.
2. Activation opens modal GTK dialog.
3. Dialog shows up to 3 items with:
   - index (`1`, `2`, `3`, newest first),
   - timestamp (human-readable local time),
   - short preview (single line, ellipsis when long),
   - `Copy` action.
4. Copy action places full text into clipboard via the existing output helper.
5. If clipboard backend is unavailable, show actionable error dialog (do not crash daemon/tray).
6. If no entries exist, show explicit empty state text.

### 5) Compatibility rules

1. Keep existing hold/release dictation flow unchanged.
2. Keep existing typing backend behavior unchanged.
3. Do not make clipboard a startup hard requirement for tray mode.
4. Use current path conventions (`Path.home()`), no hardcoded user paths.

## Code integration points

Primary files to modify:

1. `src/dictate/daemon.py`
2. `src/dictate/tray.py`

New modules:

1. `src/dictate/history.py`
2. `src/dictate/history_dialog.py`

Recommended implementation sketch:

1. Create `HistoryEntry` + `HistoryStore` in `history.py`.
2. `HistoryStore.append(text: str)`:
   - load existing,
   - prepend new entry,
   - trim to max entries (`3`),
   - atomic save.
3. Inject store into `Daemon` (`history_store` optional dependency with default).
4. In `Daemon._handle_result`, append history immediately after success checks and before `self.output.send(...)`.
5. In `TrayIcon._build_menu`, insert `Recent History...` item.
6. Add `_on_recent_history` handler that opens `RecentHistoryDialog`.
7. Implement `RecentHistoryDialog` with copy callbacks using `ClipboardOutput`.

## Test scope

### Unit tests (required)

1. `tests/test_history.py`
   - appending entries stores newest first.
   - storage trims to 3.
   - corrupted file recovers gracefully.
   - empty/missing file returns empty list.
2. `tests/test_daemon_history.py`
   - successful result appends to history.
   - non-success result does not append.
   - history append happens even if output backend raises.

### Manual verification (required)

1. Run tray mode, dictate four times, confirm only latest three shown.
2. Copy each history item and verify clipboard contents match full text.
3. Simulate wrong target/lost text, recover from history dialog.
4. Confirm app does not crash if the clipboard backend is missing; error is shown.

## Acceptance criteria

1. User can open `Recent History...` from tray utility.
2. User sees up to three most recent dictated texts with readable previews.
3. Selecting/clicking an item copies full text to clipboard.
4. Recovery works even if original paste/typing target lost text.
5. Existing dictation behavior still works exactly as before.
6. New tests pass.

## Risks and mitigations

1. Risk: Sensitive text retained on disk.
   - Mitigation: keep retention tiny (`3`) and local only; consider optional clear button in follow-up.
2. Risk: Clipboard utility unavailable on some systems.
   - Mitigation: runtime error dialog on copy action; no startup failure.
3. Risk: Corrupt JSON breaks recovery.
   - Mitigation: defensive load with empty fallback.

## Kickoff prompt for implementation agent

Use this prompt verbatim for the next coding agent:

```md
Implement the "Recent Dictation History Recovery" feature in this repository.

Read first:
- docs/archive/recent-dictation-history-spec-2026-07-05.md
- src/dictate/daemon.py
- src/dictate/tray.py
- src/dictate/hotwords_dialog.py
- src/dictate/outputs.py

Goal:
- Keep last 3 successful dictations and expose them from tray via "Recent History..." dialog.
- Clicking a history item must copy full text to clipboard for recovery.

Requirements:
1. Add persistent history store in the platform data directory.
2. Capture successful transcriptions in daemon before output send.
3. Add tray menu item "Recent History..." and GTK dialog showing up to 3 recent entries.
4. Each entry shows short preview + timestamp and has a Copy action.
5. Clipboard copy uses existing output mechanism and shows errors gracefully.
6. Do not change default dictation flow or make clipboard a startup hard dependency for tray mode.
7. Add unit tests for history store + daemon integration behavior.

Implementation notes:
- Follow existing style and path conventions (`Path.home()`).
- Keep recovery robust on missing/corrupt history file.
- Use small, clear abstractions (new module for history logic, separate dialog class).

Validation:
- Run test suite (or at minimum targeted new tests).
- Summarize changed files and any behavioral tradeoffs.
```
