// App.jsx — Note Capture shell. Home = Breath Cradle capture surface.
// The GUI is do-it-for-them: there is no settings menu. The home carries one
// control — the privacy pill (on-device vs online) — plus a Notes button; the
// only non-home view is the Notes list. All advanced config lives in the
// `dictate config` CLI. ⌘K palette = Notes + a few daily actions.
import { useState, useEffect, useRef, useCallback } from "react";
import { Icon, Mark } from "./icons.jsx";
import { Kbd, Toggle, Tooltip } from "./primitives.jsx";
import { StoreCtx, useStore, modelById, DEMO_PHRASES, formatHistoryTime, XAI_API_KEY_AGENT_INSTRUCTIONS, DICTATE_PRO_URL } from "./store.jsx";
import { VIEWS, HomeBar, NotebookToggle } from "./views.jsx";
import { ListeningHUD, CommandPalette, Toasts } from "./overlays.jsx";
import TitleBar from "./platform/TitleBar.jsx";
import { BreathCradle, WaveTimeline } from "./visualizers.jsx";
import { ipc } from "./ipc.js";
import { PRODUCT_DESTINATIONS } from "./productDestinations.js";

const DEFAULT_VERSION = "2026.7.4";
const TERMINAL_TRANSCRIPT_ID_LIMIT = 64;
const WINDOWS_PLATFORM_RE = /Windows NT|Win64|Win32|WOW64/i;
const DEMO_HISTORY = () => {
  const now = Date.now();
  // Newest-first: matches the real backend ordering and pushHistory behaviour.
  return [
    { id: "h3", createdAt: now - 6 * 60 * 1000, text: "Reminder to send the meeting summary to the team this afternoon." },
    { id: "h2", createdAt: now - 38 * 60 * 1000, text: "Let's move the planning session to Thursday and keep Friday clear for focused work." },
    { id: "h1", createdAt: now - 2 * 60 * 60 * 1000, text: "Draft a short note thanking the reviewers and ask them for feedback." },
    // A meeting (diarized segments) alongside the quick records — demonstrates the
    // Meetings/Quick category filter (see docs/record-categories-spec.md).
    {
      id: "m1",
      createdAt: now - 3 * 60 * 60 * 1000,
      text: "Weekly sync",
      segments: [
        { seq: 0, speakerLabel: "Speaker 1", tStart: 0, tEnd: 8, text: "Let's kick off with a quick status round before the roadmap." },
        { seq: 1, speakerLabel: "Speaker 2", tStart: 8, tEnd: 16, text: "Auth is done and deployed to prod; sync is the next piece." },
      ],
    },
  ];
};

// Format seconds → m:ss or h:mm:ss (mirrors the design's fmt helper).
function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}

function initialPlatform() {
  if (typeof document !== "undefined") {
    const tagged = document.documentElement.getAttribute("data-platform");
    if (tagged) return tagged;
  }
  const bridged = ipc.platform();
  if (bridged && bridged !== "gnome") return bridged;
  if (typeof navigator !== "undefined" && WINDOWS_PLATFORM_RE.test(navigator.userAgent || "")) {
    return "win11";
  }
  return bridged || "gnome";
}

function normalizeSegments(segments) {
  if (!Array.isArray(segments)) return [];
  return segments
    .map((segment, index) => {
      const text = typeof segment?.text === "string" ? segment.text.trim() : "";
      if (!text) return null;
      const tStart = Number.isFinite(Number(segment.tStart))
        ? Number(segment.tStart)
        : Number.isFinite(Number(segment.t_start))
          ? Number(segment.t_start)
          : null;
      const tEnd = Number.isFinite(Number(segment.tEnd))
        ? Number(segment.tEnd)
        : Number.isFinite(Number(segment.t_end))
          ? Number(segment.t_end)
          : null;
      return {
        seq: Number.isFinite(Number(segment.seq)) ? Number(segment.seq) : index,
        tStart,
        tEnd,
        text,
        speakerId: segment.speakerId || segment.speaker_id || null,
        speakerLabel: segment.speakerLabel || segment.speaker_label || null,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.seq - b.seq);
}

function mapHistoryPayload(history) {
  return (history || []).map((h) => ({
    id: h.id,
    text: h.text,
    createdAt: h.createdAt,
    mode: h.mode,
    status: h.status,
    segments: normalizeSegments(h.segments),
  }));
}

function noteText(note) {
  return typeof note?.text === "string" ? note.text : "";
}

function notePlainText(note) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return noteText(note);
  return segments
    .map((segment) => {
      const label = segment.speakerLabel || segment.speakerId;
      return label ? `${label}: ${segment.text}` : segment.text;
    })
    .join("\n");
}

function noteMarkdown(note, titleDate) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return `# Note - ${titleDate}\n\n${noteText(note)}\n`;
  const lines = [`# Note - ${titleDate}`, ""];
  for (const segment of segments) {
    const label = segment.speakerLabel || segment.speakerId || "Transcript";
    const hasStart = Number.isFinite(segment.tStart);
    const hasEnd = Number.isFinite(segment.tEnd);
    const time = hasStart && hasEnd
      ? ` [${fmtSecs(segment.tStart)}-${fmtSecs(segment.tEnd)}]`
      : hasStart
        ? ` [${fmtSecs(segment.tStart)}]`
        : "";
    lines.push(`**${label}${time}:** ${segment.text}`);
  }
  return `${lines.join("\n\n")}\n`;
}

/* ── Privacy control: one label + toggle on the home — where audio is transcribed. ── */
const ONLINE_MODEL = "xai/grok-speech-to-text";
// Local engine. English (Parakeet) is the private default — fast + accurate on
// this machine. Multilingual is cloud-only, so the UI only offers it as a
// cloud/Pro action rather than a regular local option.
const PRIVATE_MODEL = "parakeet/parakeet-tdt-0.6b-v2";

function cloudAvailable(s) {
  return Boolean((s.dictatePro?.signedIn && s.dictatePro?.entitlements?.active) || s.keys.xai);
}

/* Local language toggle — only shown in Private mode. English stays on-device;
   Multilingual is a cloud-only action that routes through the existing sign-in
   / Dictate Pro flow before switching providers. */
function LocalEngineToggle() {
  const s = useStore();
  const online = s.providerMode === "online";
  const privateOn = !online || s.providerDegraded;
  if (!privateOn) return null;
  const isEnglish = true;
  const pickEnglish = () => {
    if (s.model !== PRIVATE_MODEL) s.setModel(PRIVATE_MODEL);
  };
  const pickMultilingual = () => {
    s.toast("Multilingual is available in Cloud mode only.", { tone: "amber" });
    if (!cloudAvailable(s)) {
      s.toast("Cloud mode requires an active Dictate Pro subscription or personal xAI API key.", {
        bad: true,
        ms: 12_000,
        copy: XAI_API_KEY_AGENT_INSTRUCTIONS,
        href: DICTATE_PRO_URL,
      });
      return;
    }
    s.setModel(ONLINE_MODEL);
  };
  return (
    <div className="engine-seg" role="group" aria-label="Language mode">
      <button
        type="button"
        className={"engine-opt" + (isEnglish ? " on" : "")}
        aria-pressed={isEnglish}
        onClick={pickEnglish}
      >
        English
      </button>
      <button
        type="button"
        className={"engine-opt" + (!isEnglish ? " on" : "")}
        aria-pressed={false}
        onClick={pickMultilingual}
      >
        Multilingual
      </button>
    </div>
  );
}

function PrivacyPill() {
  const s = useStore();
  const online = s.providerMode === "online";
  const degraded = s.providerDegraded;
  const privateOn = !online || degraded;

  const onToggle = (on) => {
    if (on === privateOn) return;
    if (on) {
      s.setModel(PRIVATE_MODEL);
      return;
    }
    if (!cloudAvailable(s)) {
      s.toast("Requires Dictate Pro or API key.", {
        bad: true,
        ms: 12_000,
        copy: XAI_API_KEY_AGENT_INSTRUCTIONS,
        href: DICTATE_PRO_URL,
      });
      return;
    }
    s.setModel(ONLINE_MODEL);
  };

  return (
    <Tooltip label={privateOn ? "Local" : "Cloud"}>
      <div className={"privpill" + (degraded ? " degraded" : "")}>
        <Toggle on={privateOn} onChange={onToggle} />
        <span className="priv-icon" aria-label={privateOn ? "Local" : "Cloud"}>
          <Icon name={privateOn ? "laptop" : "cloud"} size={23} />
        </span>
      </div>
    </Tooltip>
  );
}

/* ── Update affordance: one quiet pill in the home bar. The primary action is
   the only thing shown; Skip / Later are revealed on proximity (hover/focus).
   Skip suppresses until a newer version; Later returns on next launch. ─────── */
const UPDATE_LABEL = {
  available: "Update available",
  downloading: "Downloading…",
  verifying: "Verifying download…",
  installing: "Installing update…",
  working: "Updating…",
  restart: "Restart Dictate",
  restarting: "Restarting…",
  error: "Update failed",
};

function formatUpdateElapsed(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function updateLabelForPhase(phase, progress, installElapsed) {
  if (phase === "downloading") {
    return Number.isFinite(progress) ? `Downloading… ${Math.round(progress)}%` : "Downloading…";
  }
  if (phase === "installing") {
    return Number.isFinite(installElapsed)
      ? `Installing update… ${formatUpdateElapsed(installElapsed)}`
      : "Installing update…";
  }
  return UPDATE_LABEL[phase] || "Update available";
}

function mapBackendUpdatePhase(status) {
  const phase = status?.phase;
  if (phase === "downloading") return "downloading";
  if (phase === "verifying") return "verifying";
  if (phase === "installing") return "installing";
  if (phase === "installed" || status?.step === "restart") return "restart";
  if (phase === "failed") return "error";
  if (phase === "working") return "working";
  return null;
}

function UpdatePill() {
  const s = useStore();
  if (!s.updateVisible) {
    return (
      <Tooltip label="Check for updates">
        <button
          type="button"
          className="upd-check"
          onClick={s.checkUpdates}
          disabled={!!s.updateStatus?.checking}
          aria-label="Check for updates"
          title="Check for updates"
        >
          <Icon name="refresh" size={15} />
        </button>
      </Tooltip>
    );
  }
  const phase = s.updatePhase;
  const label = updateLabelForPhase(phase, s.updateProgress, s.updateInstallElapsed);
  const busy = phase === "downloading" || phase === "verifying" || phase === "installing" || phase === "working";
  return (
    <div className={"updpill phase-" + phase}>
      <div className="upd-more">
        {phase === "error" ? (
          <button className="upd-mini" onClick={s.runUpdate} title="Retry update">Retry</button>
        ) : (
          <>
            <button className="upd-mini" onClick={s.dismissUpdate} title="Remind me on next launch">Later</button>
            <button className="upd-mini" onClick={s.skipUpdate} title="Skip this version">Skip</button>
          </>
        )}
      </div>
      <button
        className="upd-main"
        onClick={s.runUpdate}
        disabled={busy}
        title={
          phase === "restart" ? "Restart Dictate"
            : phase === "error" ? "Retry update"
              : busy ? label
                : "Update Dictate"
        }
      >
        <span className="upd-dot" aria-hidden="true" />
        <span className="upd-label">{label}</span>
      </button>
      {phase === "error" && s.updateErrorReason ? (
        <span className="upd-reason" role="status">{s.updateErrorReason}</span>
      ) : null}
    </div>
  );
}

function AccountButton() {
  const s = useStore();
  const syncOn = !!s.syncState?.enabled;
  return (
    <Tooltip label="Dictate">
      <button
        type="button"
        className={"account-mark" + (syncOn ? " synced" : "")}
        aria-label="Dictate account and status"
        title="Dictate account and status"
        onClick={() => s.setAccountOpen(true)}
      >
        <Mark size={17} />
      </button>
    </Tooltip>
  );
}

function syncStatusLabel({ signedIn, sync, syncBusy, syncError }) {
  if (!signedIn && !sync.accountId) return "Offline";
  if (!sync.enabled) return "Offline";
  if (!sync.keyAvailable || syncError) return "Not connected";
  if (syncBusy) return "Updating";
  return "Connected";
}

function AccountDialog() {
  const s = useStore();
  const accountPortalUrl = s.productDestinations?.hub ?? PRODUCT_DESTINATIONS.hub;
  const sync = s.syncState || { enabled: false, keyAvailable: false, lastSeq: 0 };
  const pro = s.dictatePro || { signedIn: false };
  const model = modelById(s.model);
  const signedIn = !!pro.signedIn;
  const proActive = signedIn && !!pro.entitlements?.active;
  const proStatus = pro.entitlements?.status || (signedIn ? "inactive" : "");
  const [devices, setDevices] = useState([]);
  const [recoveryKey, setRecoveryKey] = useState(null);
  const [restoreKey, setRestoreKey] = useState("");
  const [signInOpen, setSignInOpen] = useState(false);
  // Browser sign-in (loopback / device-code): {status: "idle"|"waiting"|"error", flow?, ...}.
  // Scoped to this dialog instance — polling only matters while it's open, and unmounting
  // (closing the dialog) clears the interval via the effect below.
  const [browserSignIn, setBrowserSignIn] = useState({ status: "idle" });
  const browserPollRef = useRef(null);
  // Email-code fallback form — shown directly (no "unavailable" apology) whenever browser
  // sign-in is off/unsupported, or the user picks "Email me a code instead"/"Try again".
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailStep, setEmailStep] = useState("idle"); // "idle" (enter address) | "sent" (enter code)
  const [emailAddress, setEmailAddress] = useState("");
  const [emailCode, setEmailCode] = useState("");
  const [emailChallengeId, setEmailChallengeId] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const accountLabel = pro.account?.email || pro.account?.name || sync.accountId || (signedIn ? "Signed in" : "Not signed in");
  const syncError = String(sync.lastResult?.error || sync.error || "").trim();
  const syncLabel = proActive ? syncStatusLabel({ signedIn, sync, syncBusy: s.syncBusy, syncError }) : "Offline";
  const betaSelected = s.updateChannel === "unstable";
  const storeInstall = s.updateStatus?.installKind === "windows-store";
  const updateBusy = !!(s.updateStatus?.checking || s.updateStatus?.updating);
  const offlineSyncError = syncError && /(offline|network|unreachable|failed|timeout|timed out|connection|fetch)/i.test(syncError);
  const syncedLabel = !sync.enabled
    ? "Off"
    : !sync.keyAvailable
      ? "Action needed"
      : s.syncBusy
        ? "Syncing"
        : offlineSyncError
          ? "Offline"
          : syncError
            ? "Action needed"
            : sync.lastSeq
              ? "Up to date"
              : "Starting";

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); s.setAccountOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [s]);

  useEffect(() => {
    if (!proActive || !ipc.isLive()) return;
    let cancelled = false;
    ipc.listProDevices()
      .then((r) => {
        if (!cancelled) setDevices(Array.isArray(r?.devices) ? r.devices : []);
      })
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => { cancelled = true; };
  }, [proActive]);

  const refreshAccountState = () => {
    if (!ipc.isLive()) return Promise.resolve(null);
    return ipc.getState().then((st) => {
      if (st?.dictatePro) s.setDictatePro(st.dictatePro);
      if (st?.sync) s.setSyncState(st.sync);
      if (Array.isArray(st?.history)) s.setHistory(mapHistoryPayload(st.history));
      return st;
    });
  };

  // ---- browser sign-in (loopback / device-code), with an always-working email floor ----
  const clearBrowserPoll = () => {
    if (browserPollRef.current) { clearInterval(browserPollRef.current); browserPollRef.current = null; }
  };
  // Guards setState/setInterval in async callbacks that can resolve after this dialog
  // instance has already unmounted (e.g. /browser/start is still in flight when the user
  // closes the dialog) — without it, that late resolution would both leak an interval
  // no cleanup ever clears and call setState on an unmounted component.
  const mountedRef = useRef(true);
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      clearBrowserPoll();
    };
  }, []);

  const pollBrowserSignIn = () => {
    ipc.getBrowserSignInStatus()
      .then((r) => {
        if (!mountedRef.current) return;
        if (r?.status === "pending") return;
        clearBrowserPoll();
        if (r?.status === "complete") {
          setBrowserSignIn({ status: "idle" });
          if (r.dictatePro) s.setDictatePro(r.dictatePro);
          refreshAccountState().catch(() => {});
          s.toast("Signed in");
          return;
        }
        const reason = r?.reason;
        const message = reason === "access_denied"
          ? "Sign-in was declined."
          : reason === "expired_token" || reason === "timeout"
            ? "Sign-in timed out."
            : reason && /secret store|plaintext token|keyring|secret-tool/i.test(String(reason))
              ? "Couldn't store your sign-in securely on this computer. Install libsecret-tools (secret-tool) and try again."
              : reason && reason !== "unknown" && reason !== "token_exchange_failed" && reason !== "no_pending_attempt"
                ? String(reason)
                : "Couldn't reach the sign-in service.";
        setBrowserSignIn({ status: "error", error: message });
      })
      .catch((e) => {
        if (!mountedRef.current) return;
        clearBrowserPoll();
        const raw = e && e.message ? String(e.message) : "";
        const message = /secret store|plaintext token|keyring|secret-tool/i.test(raw)
          ? "Couldn't store your sign-in securely on this computer. Install libsecret-tools (secret-tool) and try again."
          : raw && raw !== "Failed to fetch"
            ? raw
            : "Couldn't reach the sign-in service.";
        setBrowserSignIn({ status: "error", error: message });
      });
  };

  const startBrowserSignIn = (flow = "auto") => {
    if (!ipc.isLive()) {
      s.toast("Sign in from the installed app", { bad: true });
      return;
    }
    resetEmailFallback();
    clearBrowserPoll();
    ipc.startBrowserSignIn(flow)
      .then((r) => {
        if (!mountedRef.current) {
          // The dialog closed while the request was in flight — best-effort tell the
          // server to give up the pending attempt instead of orphaning it, and never
          // touch state on an unmounted component.
          ipc.cancelBrowserSignIn().catch(() => {});
          return;
        }
        if (!r || r.flow === "email") {
          // No apology — this is the normal floor, not an error state.
          setBrowserSignIn({ status: "idle" });
          setEmailOpen(true);
          return;
        }
        setBrowserSignIn({
          status: "waiting",
          flow: r.flow,
          authorizeUrl: r.authorize_url || r.authorizeUrl || null,
          userCode: r.user_code || r.userCode || null,
          verificationUri: r.verification_uri || r.verificationUri || null,
          verificationUriComplete: r.verification_uri_complete || r.verificationUriComplete || null,
        });
        browserPollRef.current = setInterval(pollBrowserSignIn, 1000);
      })
      .catch((e) => {
        if (!mountedRef.current) return;
        setBrowserSignIn({ status: "error", error: e.message || "Couldn't reach the sign-in service." });
      });
  };

  const cancelBrowserSignIn = () => {
    clearBrowserPoll();
    setBrowserSignIn({ status: "idle" });
    if (ipc.isLive()) ipc.cancelBrowserSignIn().catch(() => {});
  };

  const reopenAuthorizeUrl = () => {
    if (browserSignIn.authorizeUrl) window.open(browserSignIn.authorizeUrl, "_blank", "noopener,noreferrer");
  };

  // Belt-and-braces: the gateway's verification_uri is already scheme-clamped
  // server-side (ProClient._start_device_code / _clamp_verification_uri), but this is
  // the last line of defense before window.open — never pass through anything other
  // than https, or http on a loopback host (the local reference server).
  const isSafeVerificationUri = (url) => {
    if (!url) return false;
    if (/^https:/i.test(url)) return true;
    return /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|\?|$)/i.test(url);
  };

  const openVerificationPortal = () => {
    const url = browserSignIn.verificationUriComplete || browserSignIn.verificationUri;
    if (isSafeVerificationUri(url)) window.open(url, "_blank", "noopener,noreferrer");
  };

  const startEmailFallback = () => {
    cancelBrowserSignIn();
    setEmailOpen(true);
  };

  // Fully resets the email-code form's state (not just visibility): used whenever the
  // form is abandoned (Cancel, or switching to browser sign-in instead) so reopening it
  // later always starts a fresh challenge rather than resuming a stale code-entry step
  // against an old (possibly expired) challenge_id with no way to change the address.
  const resetEmailFallback = () => {
    setEmailOpen(false);
    setEmailStep("idle");
    setEmailAddress("");
    setEmailCode("");
    setEmailChallengeId("");
  };

  const sendEmailCode = () => {
    const email = emailAddress.trim();
    if (!email || !ipc.isLive()) return;
    setEmailBusy(true);
    ipc.startProSignIn(email)
      .then((r) => {
        setEmailChallengeId(r?.challenge_id || r?.challengeId || email);
        setEmailStep("sent");
        s.toast("Code sent — check your email");
      })
      .catch((e) => s.toast(e.message || "Could not send the code", { bad: true }))
      .finally(() => setEmailBusy(false));
  };

  const verifyEmailCode = () => {
    const code = emailCode.trim();
    if (!code || !ipc.isLive()) return;
    setEmailBusy(true);
    ipc.completeProSignIn({ challengeId: emailChallengeId, code })
      .then((r) => {
        if (r?.dictatePro) s.setDictatePro(r.dictatePro);
        resetEmailFallback();
        s.toast("Signed in");
      })
      .catch((e) => s.toast(e.message || "Could not verify the code", { bad: true }))
      .finally(() => setEmailBusy(false));
  };

  const openAccountPortal = () => {
    window.open(accountPortalUrl, "_blank", "noopener,noreferrer");
    s.toast("Opened account portal");
  };

  const signOut = () => {
    if (!ipc.isLive()) return;
    if (!window.confirm("Sign out of Dictate Pro on this device? Local dictations stay here.")) return;
    s.setSyncBusy(true);
    ipc.signOutPro()
      .then((r) => {
        s.setDictatePro({ signedIn: false, account: null });
        if (r?.sync) s.setSyncState(r.sync);
        else s.setSyncState({ enabled: false, accountId: null, deviceId: sync.deviceId || null, keyAvailable: sync.keyAvailable || false, lastSeq: sync.lastSeq || 0 });
        setDevices([]);
        s.toast("Signed out");
      })
      .catch((e) => s.toast(e.message || "Could not sign out", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const enableSync = () => {
    if (!proActive) {
      s.toast("Active Dictate Pro access is required for sync", { bad: true });
      return;
    }
    if (!ipc.isLive()) {
      s.toast("Sign in on the installed app to enable sync", { bad: true });
      return;
    }
    s.setSyncBusy(true);
    ipc.enableProSync(restoreKey.trim())
      .then((r) => {
        if (r?.sync) s.setSyncState(r.sync);
        if (r?.recoveryKey) setRecoveryKey(r.recoveryKey);
        setRestoreKey("");
        s.toast("Encrypted sync enabled");
      })
      .catch((e) => s.toast(e.message || "Could not enable sync", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const runSync = () => {
    if (!proActive) {
      s.toast("Active Dictate Pro access is required for sync", { bad: true });
      return;
    }
    if (!ipc.isLive()) return;
    s.setSyncBusy(true);
    ipc.runProSync()
      .then((r) => {
        if (r?.sync) s.setSyncState(r.sync);
        if (Array.isArray(r?.history)) s.setHistory(mapHistoryPayload(r.history));
        s.toast("Sync complete");
      })
      .catch((e) => s.toast(e.message || "Could not sync", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const setSyncScope = (scope) => {
    if ((sync.scope || "meetings") === scope) return;
    if (!ipc.isLive()) { s.setSyncState({ ...sync, scope }); return; }
    s.setSyncBusy(true);
    ipc.setProSyncScope(scope)
      .then((r) => { const st = r?.sync || r; if (st) s.setSyncState(st); })
      .catch((e) => s.toast(e.message || "Could not change sync scope", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const disableSync = () => {
    if (!ipc.isLive()) {
      s.setSyncState({ enabled: false, accountId: null, deviceId: null, keyAvailable: false, lastSeq: 0 });
      return;
    }
    s.setSyncBusy(true);
    ipc.disableProSync(false)
      .then((r) => {
        if (r?.sync) s.setSyncState(r.sync);
        s.toast("Sync disabled");
      })
      .catch((e) => s.toast(e.message || "Could not disable sync", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const refreshDevices = () => {
    if (!ipc.isLive()) return;
    ipc.listProDevices()
      .then((r) => setDevices(Array.isArray(r?.devices) ? r.devices : []))
      .catch((e) => s.toast(e.message || "Could not load devices", { bad: true }));
  };

  const revokeDevice = (deviceId) => {
    if (!deviceId || !ipc.isLive()) return;
    if (!window.confirm("Remove this device from Dictate Pro sync?")) return;
    s.setSyncBusy(true);
    ipc.revokeProDevice(deviceId)
      .then(() => {
        s.toast("Device removed");
        refreshDevices();
      })
      .catch((e) => s.toast(e.message || "Could not remove device", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const approveDevice = (deviceId) => {
    if (!deviceId || !ipc.isLive()) return;
    s.setSyncBusy(true);
    ipc.approveProDevice(deviceId)
      .then(() => {
        s.toast("Device approved");
        refreshDevices();
      })
      .catch((e) => s.toast(e.message || "Could not approve device", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const exportCloudData = () => {
    if (!ipc.isLive()) return;
    s.setSyncBusy(true);
    ipc.exportProCloudData()
      .then((data) => ipc.saveTextFile("dictate-pro-cloud-export.json", JSON.stringify(data, null, 2)))
      .then(() => s.toast("Cloud export saved"))
      .catch((e) => s.toast(e.message || "Could not export cloud data", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const deleteCloudData = () => {
    if (!ipc.isLive()) return;
    if (!window.confirm("Delete Dictate Pro cloud data for this account? Local notes stay on this device.")) return;
    s.setSyncBusy(true);
    ipc.deleteProCloudData()
      .then((r) => {
        if (r?.sync) s.setSyncState(r.sync);
        setDevices([]);
        s.toast("Cloud data deleted");
      })
      .catch((e) => s.toast(e.message || "Could not delete cloud data", { bad: true }))
      .finally(() => s.setSyncBusy(false));
  };

  const selectUpdateChannel = (channel) => {
    if (channel === s.updateChannel) return;
    if (!ipc.isLive()) {
      s.setUpdateChannel(channel);
      s.toast(channel === "unstable" ? "Beta updates selected" : "Normal updates selected");
      return;
    }
    ipc.setUpdateChannel(channel)
      .then((st) => {
        if (st?.updateChannel) s.setUpdateChannel(st.updateChannel);
        if (typeof st?.installedPackageVersion === "string") s.setInstalledPackageVersion(st.installedPackageVersion);
        s.toast(channel === "unstable" ? "Beta updates selected" : "Normal updates selected");
        s.checkUpdates();
      })
      .catch((e) => s.toast(e.message || "Could not change update channel", { bad: true }));
  };

  return (
    <div className="account-scrim" onMouseDown={() => s.setAccountOpen(false)}>
      <div
        className="account-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="account-head">
          <span className="account-logo"><Mark size={22} /></span>
          <div className="account-title-wrap">
            <div id="account-title" className="account-title">Dictate</div>
            <div className="account-sub">Version {s.version}{s.updateChannel ? ` · ${s.updateChannel}` : ""}</div>
          </div>
          <button type="button" className="ibtn" aria-label="Close" title="Close" onClick={() => s.setAccountOpen(false)}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="account-grid">
          <div className="account-row">
            <span>Account</span>
            {signedIn ? (
              <strong>{accountLabel}</strong>
            ) : (
              <div className="account-row-end">
                <strong>Not signed in</strong>
                {!signInOpen && (
                  <button type="button" className="account-signin" disabled={s.syncBusy} onClick={() => setSignInOpen(true)}>
                    Account
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="account-row"><span>Sync</span><strong>{syncLabel}</strong></div>
          {signedIn && (
            <div className="account-row"><span>Plan</span><strong>{proActive ? (pro.entitlements?.display_name || "Dictate Pro") : proStatus}</strong></div>
          )}
          <div className="account-row"><span>Model</span><strong>{model.name}</strong></div>
          {s.installedPackageVersion && (
            <div className="account-row"><span>Package</span><strong>{s.installedPackageVersion}</strong></div>
          )}
          <div className="account-row">
            <span>Updates</span>
            {storeInstall ? <strong>Microsoft Store · Stable</strong> : <div className="account-channel" role="group" aria-label="Update channel">
              <button
                type="button"
                className={!betaSelected ? "active" : ""}
                aria-pressed={!betaSelected}
                onClick={() => selectUpdateChannel("stable")}
              >
                Normal
              </button>
              <button
                type="button"
                className={betaSelected ? "active" : ""}
                aria-pressed={betaSelected}
                title="Beta updates"
                onClick={() => selectUpdateChannel("unstable")}
              >
                Beta
              </button>
            </div>}
          </div>
          {sync.enabled && (
            <div className="account-row"><span>Synced</span><strong>{syncedLabel}</strong></div>
          )}
          {sync.enabled && (
            <div className="account-row">
              <span>Sync scope</span>
              <div className="account-channel" role="group" aria-label="Sync scope">
                <button
                  type="button"
                  className={(sync.scope || "meetings") === "meetings" ? "active" : ""}
                  aria-pressed={(sync.scope || "meetings") === "meetings"}
                  disabled={s.syncBusy}
                  title="Sync meetings only"
                  onClick={() => setSyncScope("meetings")}
                >
                  Meetings
                </button>
                <button
                  type="button"
                  className={(sync.scope || "meetings") === "everything" ? "active" : ""}
                  aria-pressed={(sync.scope || "meetings") === "everything"}
                  disabled={s.syncBusy}
                  title="Also sync the rolling quick-copy history"
                  onClick={() => setSyncScope("everything")}
                >
                  Everything
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="account-actions account-actions--split">
          <button type="button" className="account-secondary" disabled={updateBusy} onClick={s.checkUpdates}>
            <Icon name="refresh" size={14} />
            <span>{s.updateStatus?.checking ? "Checking" : "Check for update"}</span>
          </button>
          {s.updateStatus?.updateAvailable && (
            <button type="button" className="account-primary" disabled={updateBusy} onClick={s.startUpdate}>
              <Icon name="download" size={14} />
              <span>{s.updateStatus?.updating ? "Updating" : "Update"}</span>
            </button>
          )}
        </div>

        {(signedIn || signInOpen) && (
        <div className="account-actions">
          {!signedIn ? (
            <div className="account-enable-stack">
              {browserSignIn.status === "waiting" && browserSignIn.flow === "loopback" ? (
                <>
                  <div className="account-consent">
                    <strong>Waiting for browser…</strong>
                    <span>Approve the sign-in in the browser tab we just opened.</span>
                  </div>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={reopenAuthorizeUrl}>
                    Open sign-in page
                  </button>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={() => startBrowserSignIn("device_code")}>
                    Use a code instead
                  </button>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={cancelBrowserSignIn}>
                    Cancel
                  </button>
                </>
              ) : browserSignIn.status === "waiting" && browserSignIn.flow === "device_code" ? (
                <>
                  <div className="account-recovery">
                    <span>Enter this code at your account portal</span>
                    <code>{browserSignIn.userCode}</code>
                  </div>
                  <button type="button" className="account-primary" disabled={s.syncBusy} onClick={openVerificationPortal}>
                    Open portal
                  </button>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={cancelBrowserSignIn}>
                    Cancel
                  </button>
                </>
              ) : browserSignIn.status === "error" ? (
                <>
                  <div className="account-note bad">{browserSignIn.error}</div>
                  <button type="button" className="account-primary" disabled={s.syncBusy} onClick={() => startBrowserSignIn("auto")}>
                    Try again
                  </button>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={startEmailFallback}>
                    Email me a code
                  </button>
                </>
              ) : emailOpen ? (
                <>
                  <div className="account-consent">
                    <strong>Sign in with an email code</strong>
                    <span>We'll email a code to sign in this device.</span>
                  </div>
                  {emailStep === "idle" ? (
                    <>
                      <input
                        className="account-input"
                        value={emailAddress}
                        onChange={(e) => setEmailAddress(e.target.value)}
                        placeholder="Email address"
                        aria-label="Email address"
                      />
                      <button
                        type="button"
                        className="account-primary"
                        disabled={s.syncBusy || emailBusy || !emailAddress.trim()}
                        onClick={sendEmailCode}
                      >
                        Send code
                      </button>
                    </>
                  ) : (
                    <>
                      <input
                        className="account-input"
                        value={emailCode}
                        onChange={(e) => setEmailCode(e.target.value)}
                        placeholder="Code from email"
                        aria-label="Sign-in code"
                      />
                      <button
                        type="button"
                        className="account-primary"
                        disabled={s.syncBusy || emailBusy || !emailCode.trim()}
                        onClick={verifyEmailCode}
                      >
                        Verify code
                      </button>
                    </>
                  )}
                  <button type="button" className="account-secondary" disabled={s.syncBusy || emailBusy} onClick={resetEmailFallback}>
                    Cancel
                  </button>
                </>
              ) : !s.browserSigninEnabled ? (
                // Flag off: don't promise a browser this build won't open — the primary
                // action goes straight to the email-code floor with honest copy.
                <>
                  <div className="account-consent">
                    <strong>Sign in to your account</strong>
                    <span>We'll email you a code to sign in this device.</span>
                  </div>
                  <button type="button" className="account-primary" disabled={s.syncBusy} onClick={() => setEmailOpen(true)}>
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  <div className="account-consent">
                    <strong>Sign in to your account</strong>
                    <span>Opens your browser to connect this device to your account.</span>
                  </div>
                  <button type="button" className="account-primary" disabled={s.syncBusy} onClick={() => startBrowserSignIn("auto")}>
                    Sign in
                  </button>
                  <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={() => setEmailOpen(true)}>
                    Email me a code instead
                  </button>
                </>
              )}
            </div>
          ) : !proActive ? (
            <div className="account-enable-stack">
              <div className="account-consent">
                <strong>Dictate Pro access required</strong>
                <span>This account is signed in, but cloud sync and Beta updates are not active on its plan.</span>
              </div>
            </div>
          ) : !sync.enabled ? (
            <div className="account-enable-stack">
              <div className="account-consent">
                <strong>Sync my dictations across devices</strong>
                <span>This encrypts your synced dictations before upload.</span>
              </div>
              <input
                className="account-input"
                value={restoreKey}
                onChange={(e) => setRestoreKey(e.target.value)}
                placeholder="Recovery key"
                aria-label="Recovery key"
              />
              <button type="button" className="account-primary" disabled={s.syncBusy || !proActive} onClick={enableSync}>
                <Icon name="lock" size={14} />
                <span>{restoreKey.trim() ? "Restore sync" : "Sync my dictations"}</span>
              </button>
            </div>
          ) : (
            <>
              <button type="button" className="account-primary" disabled={s.syncBusy || !sync.keyAvailable} onClick={runSync}>
                <Icon name="refresh" size={14} />
                <span>Sync now</span>
              </button>
              <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={disableSync}>
                Disable
              </button>
            </>
          )}
        </div>
        )}
        {recoveryKey && (
          <div className="account-recovery">
            <span>Recovery key</span>
            <p>Save this key. It restores synced dictations on a new device if your other devices are unavailable.</p>
            <code>{recoveryKey}</code>
          </div>
        )}
        {signedIn && proActive && (
          <>
            <div className="account-section-title">Devices</div>
            <div className="account-device-list">
              {devices.length ? devices.map((device) => {
                const id = device.device_id || device.deviceId;
                const isThis = id && sync.deviceId && id === sync.deviceId;
                const revoked = !!(device.revoked_at || device.revokedAt);
                const trusted = !!(device.trusted_at || device.trustedAt);
                const status = isThis ? "This device" : revoked ? "Removed" : trusted ? "Active" : "Action needed";
                return (
                  <div className="account-device" key={id || device.label || "device"}>
                    <div>
                      <strong>{device.label || (isThis ? "This device" : "Desktop")}</strong>
                      <span>{status}</span>
                    </div>
                    {!isThis && !revoked && (
                      <div className="account-device-actions">
                        {!trusted && (
                          <button type="button" className="account-primary mini" disabled={s.syncBusy || !sync.keyAvailable} onClick={() => approveDevice(id)}>
                            Approve
                          </button>
                        )}
                        <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={() => revokeDevice(id)}>
                          Remove
                        </button>
                      </div>
                    )}
                  </div>
                );
              }) : (
                <div className="account-empty">No devices to show.</div>
              )}
            </div>
            <div className="account-actions account-actions--split">
              <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={exportCloudData}>
                Export my data
              </button>
              <button type="button" className="account-danger" disabled={s.syncBusy} onClick={deleteCloudData}>
                Delete cloud data
              </button>
            </div>
          </>
        )}
        {signedIn && (
          <div className="account-actions account-actions--split">
            <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={openAccountPortal}>
              Manage account
            </button>
            <button type="button" className="account-secondary" disabled={s.syncBusy} onClick={signOut}>
              Sign out
            </button>
          </div>
        )}
        {!signedIn && <div className="account-note">Cloud sync needs a signed-in desktop session.</div>}
        {signedIn && proActive && <div className="account-note">Hosted Pro transcription is separate from sync and may send audio to hosted model providers when selected.</div>}
        {signedIn && !proActive && <div className="account-note">This account is signed in but does not currently have active Dictate Pro access. Cloud sync is off.</div>}
        {sync.enabled && !sync.keyAvailable && <div className="account-note bad">The encryption key is missing from this device.</div>}
      </div>
    </div>
  );
}

function DiscardConfirmDialog({ meeting, onCancel, onConfirm }) {
  const confirmRef = useRef(null);
  useEffect(() => {
    const t = setTimeout(() => confirmRef.current?.focus(), 40);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onCancel(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const label = meeting ? "meeting" : "note";
  return (
    <div className="confirm-scrim" onMouseDown={onCancel}>
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="discard-title"
        aria-describedby="discard-desc"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div id="discard-title" className="confirm-title">Discard {label}?</div>
        <div id="discard-desc" className="confirm-desc">
          This recording will be deleted and won&apos;t be saved to your notes.
        </div>
        <div className="confirm-actions">
          <button type="button" className="confirm-secondary" onClick={onCancel}>Cancel</button>
          <button ref={confirmRef} type="button" className="confirm-danger" autoFocus onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}

/* ── Getting-started keyboard: a quiet, aligned keyboard graphic that points at
   Right Ctrl. Shown on the empty home (no notes yet) to teach the one key. ──── */
function GsKeyboard() {
  const row = (n) => Array.from({ length: n }, (_, i) => <span className="k" key={i} />);
  return (
    <div className="gs-kbd" aria-hidden="true">
      <div className="gs-row fn">{row(13)}</div>
      <div className="gs-row">{row(13)}</div>
      <div className="gs-row">{row(11)}<span className="k wide" /></div>
      <div className="gs-row"><span className="k wide" />{row(9)}<span className="k wide" /></div>
      <div className="gs-row">
        <span className="k" /><span className="k" /><span className="k" />
        <span className="k space" /><span className="k" /><span className="k hot">Ctrl</span>
        <span className="gs-arrows">
          <span className="ar-top"><i className="ak" /></span>
          <span className="ar-bot"><i className="ak" /><i className="ak" /><i className="ak" /></span>
        </span>
      </div>
    </div>
  );
}

/* ── Capture home: header + Breath Cradle + feedback ─────────────────── */
function CaptureHome() {
  const s = useStore();
  const meeting = s.captureMode === "meeting";
  const [discardOpen, setDiscardOpen] = useState(false);
  // Getting-started teaching is per-session, not per-history: it shows on every
  // fresh launch (even with saved notes) and hides once capture begins this run.
  const gettingStarted = !s.noteRecording && !s.sessionStarted;
  // Copy-last: the most recent quick record (a dictation, not a diarized meeting).
  const isMeeting = (n) => n?.mode === "meeting"
    || (n?.mode == null && Array.isArray(n?.segments) && n.segments.length > 0);
  const recentQuick = (s.history || []).find((n) => !isMeeting(n));
  const recentQuickText = recentQuick ? (recentQuick.text || notePlainText(recentQuick)) : "";
  const recentQuickPreview = recentQuickText;
  const copyLast = () => {
    if (!recentQuickText) return;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(recentQuickText)
        .then(() => s.toast("Copied last dictation"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };
  useEffect(() => {
    if (!s.noteRecording || !s.notePaused) setDiscardOpen(false);
  }, [s.noteRecording, s.notePaused]);
  return (
    <div className="note-home">
      {/* Home chrome: the privacy truth (the one human control) + Notes. No gear —
          the GUI is do-it-for-them; advanced config lives in `dictate config`. */}
      <HomeBar
        left={<><PrivacyPill /><LocalEngineToggle /></>}
        right={<><UpdatePill /><AccountButton /></>}
        meeting={!s.noteRecording ? (
          <button type="button" className="meeting-action" onClick={s.startMeetingRecording}>
            <Icon name="users" size={14} />
            <span>Meeting</span>
          </button>
        ) : null}
      />
      <div className="note-home-inner">
        {/* Cradle + feedback */}
        <div className="note-screen">
          <div className="note-capture-stack">
            <div className="note-capture-anchor">
              {/* cradle-wrap: positions the one-shot flash ring relative to the cradle */}
              <div className="cradle-wrap">
                {s.flash && (
                  <span className={"flashring " + s.flash.to} key={s.flash.id} aria-hidden="true" />
                )}
                <BreathCradle
                  session={s.noteRecording}
                  active={s.noteRecording && !s.notePaused}
                  paused={s.notePaused}
                  reduced={s.reduced}
                  onStart={s.startNoteRecording}
                  onPause={meeting ? s.finishNoteRecording : s.pauseNoteRecording}
                  onResume={s.resumeNoteRecording}
                  activeLabel={meeting ? "Finish meeting" : "Pause recording"}
                />
              </div>
              <div className={"note-feedback" + (gettingStarted ? " note-feedback--intro" : "")}>
            {s.noteRecording && !s.notePaused ? (
              <>
                <div className="note-status live">{meeting ? "Meeting" : "Recording"}</div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                {s.transcript?.text ? (
                  <div className="note-preview" aria-live="polite">
                    <span>{s.transcript.text}</span><span className="note-caret" />
                  </div>
                ) : (
                  <WaveTimeline active reduced={s.reduced} level={s.audioLevel} live={s.live} />
                )}
              </>
            ) : s.noteRecording && s.notePaused ? (
              <>
                <div className="note-status paused">
                  {s.notePauseReason === "silence" ? "Paused — no speech detected" : "Paused"}
                </div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                <div className="note-finish-row">
                  <button type="button" className="note-finish-btn" onClick={s.finishNoteRecording}>
                    <Icon name="square" size={14} />
                    <span>{meeting ? "Finish meeting" : "Finish note"}</span>
                  </button>
                  <button
                    type="button"
                    className="note-discard-btn"
                    aria-label="Discard recording"
                    title="Discard"
                    onClick={() => setDiscardOpen(true)}
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="note-status-sub t-mono">Click to dictate</div>
                {/* Getting started (per-session): teach the key on a fresh launch. */}
                {gettingStarted && (
                  <>
                    <div className="note-status-hint t-mono">or hold {s.shortcut.join(" + ")}</div>
                    <GsKeyboard />
                  </>
                )}
                {/* Once capture has begun this session, offer a one-click copy of the
                    most recent quick dictation (older ones live in the notes list). */}
                {s.sessionStarted && recentQuickText && (
                  <button type="button" className="note-copylast t-mono" onClick={copyLast}>
                    <Icon name="copy" size={13} />
                    <span className="note-copylast-content">
                      <span className="note-copylast-label">Copy last dictation</span>
                      <span className="note-copylast-preview">{recentQuickPreview}</span>
                    </span>
                  </button>
                )}
                {/* Live push-to-talk transcript — hide once history has the same note. */}
                {s.transcript?.text && !s.transcript.stale && (s.recording || !s.history?.length) && (
                  <div className="note-preview" aria-live="polite">
                    <span>{s.transcript.text}</span>
                    {s.recording && <span className="note-caret" />}
                  </div>
                )}
              </>
            )}
              </div>
            </div>
          </div>
          {/* Degraded recording strip: amber, visible while recording on local fallback */}
          {s.noteRecording && !s.notePaused && s.providerDegraded && (
            <div className="note-longstrip amber t-mono">
              <span className="wdot" />
              On-device · reconnecting…
            </div>
          )}
        </div>
      </div>
      {discardOpen && (
        <DiscardConfirmDialog
          meeting={meeting}
          onCancel={() => setDiscardOpen(false)}
          onConfirm={() => {
            setDiscardOpen(false);
            s.discardNoteRecording();
          }}
        />
      )}
    </div>
  );
}

/* ── Transcribing… (indeterminate, shown between stop and note event) ── */
function NoteProcessing() {
  const s = useStore();
  const meeting = s.captureMode === "meeting";
  return (
    <div className="note-proc-wrap">
      <div className="note-proc-inner">
        <div className="note-status" style={{ marginBottom: 6 }}>Transcribing…</div>
        <div className="note-status-sub t-mono">
          {meeting ? "Separating speakers and preparing the transcript." : "Turning your words into a note."}
        </div>
        <div className="note-proc-bar" aria-hidden="true"><span /></div>
      </div>
    </div>
  );
}

/* ── Expanded note: full scrollable text + Copy / Export ──────────────── */
function ExpandedNote() {
  const s = useStore();
  const note = s.currentNote;
  if (!note) return null;

  const noteLabel = note.createdAt ? `Note · ${formatHistoryTime(note.createdAt)}` : "Note";

  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(notePlainText(note))
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  // Export dictation as a Markdown file via the OS save dialog.
  const handleExport = async () => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const name = `dictate-note-${ts}.md`;
    const md = noteMarkdown(note, ts);
    try {
      const saved = await ipc.saveTextFile(name, md);
      if (saved) s.toast("Saved as Markdown");
    } catch {
      s.toast("Could not save file", { bad: true });
    }
  };

  const closeExpanded = () => {
    s.setNoteView(null);
    s.setView(s.expandedFrom === "history" ? "history" : "home");
  };

  const backLabel = s.expandedFrom === "history" ? "Back to dictations" : "Back to capture";

  return (
    <div className="note-exp-wrap">
      <div className="notes-search note-exp-top">
        <span className="note-exp-title">{noteLabel}</span>
        <span className="notes-search-grow" aria-hidden="true" />
        <button className="ibtn" title="Copy" onClick={handleCopy}><Icon name="copy" size={16} /></button>
        <button className="ibtn" title="Export as Markdown" onClick={handleExport}><Icon name="download" size={16} /></button>
        <NotebookToggle />
      </div>
      <div className="note-exp-body">
        <button
          type="button"
          className="note-exp-back-col"
          aria-label={backLabel}
          title={backLabel}
          onClick={closeExpanded}
        >
          <span className="note-exp-back-ico" aria-hidden="true">
            <Icon name="back" size={18} />
          </span>
        </button>
        <div className="note-exp-scroll scroll">
        {normalizeSegments(note.segments).length > 0 ? (
          <div className="note-segments">
            {normalizeSegments(note.segments).map((segment) => {
              const label = segment.speakerLabel || segment.speakerId;
              const hasStart = Number.isFinite(segment.tStart);
              const hasEnd = Number.isFinite(segment.tEnd);
              return (
                <div className="note-segment" key={segment.seq}>
                  {label && <span className="note-segment-speaker">{label}</span>}
                  {(hasStart || hasEnd) && (
                    <span className="note-segment-time">
                      {hasStart ? fmtSecs(segment.tStart) : "--"}
                      {hasEnd ? `-${fmtSecs(segment.tEnd)}` : ""}
                    </span>
                  )}
                  <p className="note-segment-text">{segment.text}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="note-exp-text">{noteText(note)}</p>
        )}
        </div>
      </div>
    </div>
  );
}

/* ======================================================================
   App — root component
   ====================================================================== */
export default function App() {
  // "home" = Breath Cradle capture surface; any VIEWS key = that settings view.
  const [view, setView] = useState("home");
  const [model, setModelState] = useState(PRIVATE_MODEL);
  const [meetingModel, setMeetingModelState] = useState("parakeet-pyannote/parakeet-tdt-0.6b-v2");
  const [meetingReadiness, setMeetingReadiness] = useState({ ready: true, reason: null });
  const [keys, setKeys] = useState({ openai: false, xai: false, gemini: false });
  const [shortcut, setShortcutState] = useState(["Ctrl (R)"]);
  const [activation, setActivationState] = useState("hold");
  const [device] = useState("Default device");
  const [device2, setDevice2State] = useState("auto");
  const [compute, setComputeState] = useState("int8");
  const [hotwords, setHotwords] = useState([]);
  const [history, setHistory] = useState(() => (ipc.isMockMode() ? DEMO_HISTORY() : []));
  // Default to system color scheme when no explicit pref is saved (Stage 3 parity with prototype).
  const [theme, setThemeState] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [startup, setStartupState] = useState(true);
  const [trayOnly, setTrayOnlyState] = useState(true);
  const [overlay, setOverlayState] = useState(true);
  const [sound, setSoundState] = useState(false);
  const [ambient, setAmbientState] = useState(true);
  const [recording, setRecording] = useState(false);
  const [noteRecording, setNoteRecording] = useState(false);
  // Session-scoped: false on a fresh launch, true once the user has captured
  // anything this run. Not persisted — resets to false on app close/reopen, so
  // the getting-started teaching re-shows and the home copy-last hides again.
  const [sessionStarted, setSessionStarted] = useState(false);
  const [notePaused, setNotePaused] = useState(false);
  const [notePauseReason, setNotePauseReason] = useState(null);
  const [captureMode, setCaptureMode] = useState("note");
  const [noteText, setNoteText] = useState("");
  const [noteElapsed, setNoteElapsed] = useState(0); // seconds since noteRecording started
  const [audioLevel, setAudioLevel] = useState(null);
  const [transcript, setTranscript] = useState({ phase: null, text: "", stale: false });
  const [typing, setTyping] = useState(false);
  const [targetText, setTargetText] = useState("");
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [capturing, setCapturing] = useState(false);
  const [version, setVersion] = useState(DEFAULT_VERSION);
  const [updateChannel, setUpdateChannel] = useState("stable");
  const [installedPackageVersion, setInstalledPackageVersion] = useState("");
  const [updateStatus, setUpdateStatus] = useState(() => mockUpdateStatus(DEFAULT_VERSION));
  // Update affordance state machine: idle → available → preparing → ready → installing (→ error).
  // The update prepares in the background so the click is instant once "ready".
  const [updatePhase, setUpdatePhase] = useState("idle");
  const [updateProgress, setUpdateProgress] = useState(null);
  const [updateInstallStartedAt, setUpdateInstallStartedAt] = useState(null);
  const [updateInstallElapsed, setUpdateInstallElapsed] = useState(null);
  const [updateErrorReason, setUpdateErrorReason] = useState(null);
  // Skip persists across launches (suppress until a newer version); Dismiss is session-only.
  const [skippedVersion, setSkippedVersion] = useState(() => {
    try { return (typeof localStorage !== "undefined" && localStorage.getItem("dictate.skippedVersion")) || null; }
    catch { return null; }
  });
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [platform, setPlatform] = useState(initialPlatform);
  const [live, setLive] = useState(false);
  // Note surface state machine: null=home, "processing"=transcribing, "expanded"=full note view
  const [noteView, setNoteView] = useState(null);
  const [currentNote, setCurrentNote] = useState(null);
  // Provider health: on-device is always-available floor; degraded = fell back from the online provider.
  const [providerHealthy, setProviderHealthy] = useState(true);
  const [providerStatus, setProviderStatus] = useState("ok");
  const [providerMode, setProviderMode] = useState("private");
  const [providerDegraded, setProviderDegraded] = useState(false);
  const [providerReason, setProviderReason] = useState(null);
  const [providerActive, setProviderActive] = useState(null);
  const [dictatePro, setDictatePro] = useState({ signedIn: false });
  const [productDestinations, setProductDestinations] = useState(PRODUCT_DESTINATIONS);
  const [browserSigninEnabled, setBrowserSigninEnabled] = useState(false);
  const [syncState, setSyncState] = useState({ enabled: false, accountId: null, deviceId: null, keyAvailable: false, lastSeq: 0 });
  const [syncBusy, setSyncBusy] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  // flash: one-shot ring pulse on provider switch (local=amber, remote=green). Never silent.
  const [flash, setFlash] = useState(null);
  // expandedFrom: where the expanded view was opened from — "capture" (just dictated) or
  // "history" (notes list).
  const [expandedFrom, setExpandedFrom] = useState("capture");

  // Detect prefers-reduced-motion for the BreathCradle.
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e) => setReduced(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Track whether the user has explicitly picked a theme (Light/Dark via gear or loaded from prefs).
  // Only the system follower uses this; an explicit pick must always win.
  const explicitThemeRef = useRef(false);

  // Live-follow the OS color scheme, but only when no explicit user pref is set — mirrors the
  // reduced-motion listener pattern. An explicit pick (or a saved pref on hydration) locks the theme.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e) => {
      if (!explicitThemeRef.current) setThemeState(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // ---- refs to dodge stale closures in global listeners ----
  const recRef = useRef(false); recRef.current = recording;
  const tgtRef = useRef(""); tgtRef.current = targetText;
  const actRef = useRef(activation); actRef.current = activation;
  const capRef = useRef(false); capRef.current = capturing;
  const providerModeRef = useRef("private"); providerModeRef.current = providerMode;
  const transcriptIdRef = useRef(null);
  const terminalTranscriptIdsRef = useRef(new Set());
  const terminalTranscriptIdOrderRef = useRef([]);
  // noteViewRef: stale-closure-safe read of noteView inside the SSE handler.
  const noteViewRef = useRef(null); noteViewRef.current = noteView;
  const discardPendingRef = useRef(false);
  const captureModeRef = useRef("note"); captureModeRef.current = captureMode;
  // watchdogRef: 60 s safety-net timer; cleared on every normal resolution path.
  const watchdogRef = useRef(null);
  // Flash ring: stable refs so triggerFlash can be useCallback([]) and safe in SSE handler.
  const flashIdRef = useRef(0);
  const flashTimerRef = useRef(null);
  const ARCHIVE_LEAVE_MS = 220;
  const ARCHIVE_UNDO_LIMIT = 20;
  const [leavingNoteIds, setLeavingNoteIds] = useState([]);
  const leavingNoteIdsRef = useRef(new Set());
  const archiveUndoRef = useRef([]);
  const archiveTimersRef = useRef(new Map());
  const currentNoteRef = useRef(null); currentNoteRef.current = currentNote;
  const expandedFromRef = useRef("capture"); expandedFromRef.current = expandedFrom;
  const updatePollRef = useRef(null);
  const updatePollModeRef = useRef(null);
  const updateRestartRequestedRef = useRef(false);

  const stopUpdatePolling = () => {
    if (updatePollRef.current) {
      clearInterval(updatePollRef.current);
      updatePollRef.current = null;
    }
    updatePollModeRef.current = null;
  };

  const requestUpdateRestart = (message) => {
    if (updateRestartRequestedRef.current) return;
    updateRestartRequestedRef.current = true;
    setUpdatePhase("restarting");
    setUpdateProgress(null);
    setUpdateErrorReason(null);
    stopUpdatePolling();
    if (message) toast(message);
    Promise.resolve(ipc.restartApp()).then((restarted) => {
      if (restarted) return;
      updateRestartRequestedRef.current = false;
      setUpdatePhase("restart");
      toast("Restart Dictate to finish the update", { bad: true });
    }).catch(() => {
      updateRestartRequestedRef.current = false;
      setUpdatePhase("restart");
      toast("Restart Dictate to finish the update", { bad: true });
    });
  };

  const applyPolledUpdateStatus = (status) => {
    if (!status) return;
    setUpdateStatus((u) => ({ ...u, ...status, checking: false, updating: false }));
    const mapped = mapBackendUpdatePhase(status);
    if (mapped === "downloading") {
      setUpdatePhase("downloading");
      setUpdateProgress(Number.isFinite(status.progress) ? status.progress : null);
      setUpdateErrorReason(null);
      return;
    }
    if (mapped === "verifying") {
      setUpdatePhase("verifying");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      return;
    }
    if (mapped === "installing") {
      setUpdatePhase("installing");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      if (status.installStartedAt) setUpdateInstallStartedAt(status.installStartedAt);
      return;
    }
    if (mapped === "restart") {
      requestUpdateRestart("Update installed — restarting…");
      return;
    }
    if (mapped === "error") {
      setUpdatePhase("error");
      setUpdateProgress(null);
      setUpdateErrorReason(status.errorDetail || status.error || "Update failed");
      stopUpdatePolling();
      return;
    }
    if (updatePollModeRef.current === "command" && status.checked && !status.updateAvailable) {
      setUpdatePhase("restart");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      stopUpdatePolling();
    }
  };

  const startUpdatePolling = (mode = "package") => {
    stopUpdatePolling();
    updatePollModeRef.current = mode;
    updatePollRef.current = setInterval(() => {
      if (!ipc.isLive()) return;
      ipc.checkUpdates().then(applyPolledUpdateStatus).catch(() => {});
    }, 1000);
  };

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.setAttribute("data-ambient", ambient ? "on" : "off"); }, [ambient]);

  useEffect(() => {
    if (updatePhase !== "installing" || !updateInstallStartedAt) {
      if (updatePhase !== "installing") setUpdateInstallElapsed(null);
      return;
    }
    const started = Date.parse(updateInstallStartedAt);
    const tick = () => {
      if (!Number.isFinite(started)) return;
      setUpdateInstallElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [updatePhase, updateInstallStartedAt]);

  useEffect(() => () => stopUpdatePolling(), []);

  // ---- note-recording elapsed timer ----
  useEffect(() => {
    if (!noteRecording || notePaused) { if (!noteRecording) setNoteElapsed(0); return; }
    const id = setInterval(() => setNoteElapsed((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [noteRecording, notePaused]);

  // ---- hydrate from the engine + subscribe to live events ----
  useEffect(() => {
    setPlatform(ipc.platform());
    if (!ipc.isLive()) return;
    setLive(true);
    let cancelled = false;
    ipc.getState().then((st) => {
      if (cancelled || !st) return;
      hydrate(st);
    }).catch(() => {});
    const unsub = ipc.subscribe((ev) => {
      if (ev.type === "recording") {
        setRecording(!!ev.active);
        if (ev.active) setSessionStarted(true);
        if (ev.active) setTranscript({ phase: null, text: "", stale: false });
        else setAudioLevel(null);
      }
      else if (ev.type === "note-recording") {
        if (ev.paused) {
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          setNoteRecording(true);
          setNotePaused(true);
          setNotePauseReason(ev.pauseReason || null);
          setAudioLevel(null);
        } else if (ev.active) {
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          setNoteRecording(true);
          setSessionStarted(true);
          setNotePaused(false);
          setNotePauseReason(null);
          setAudioLevel(null);
          // New recording started — clear any stale watchdog, reset note surface.
          clearWatchdog();
          setNoteView(null);
          setCurrentNote(null);
        } else {
          setNoteRecording(false);
          setNotePaused(false);
          setNotePauseReason(null);
          setAudioLevel(null);
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          if (ev.discarded || discardPendingRef.current) {
            discardPendingRef.current = false;
            clearWatchdog();
            setNoteView(null);
            setCurrentNote(null);
            setTranscript({ phase: null, text: "", stale: false });
          } else {
            // Recording finished — show Transcribing… and arm the safety-net watchdog.
            setNoteView("processing");
            armWatchdog();
          }
        }
      }
      else if (ev.type === "audio-level") {
        if (typeof ev.level === "number") setAudioLevel(ev.level);
      }
      else if (ev.type === "note") {
        // The backend now sends a `status` field on every terminal note outcome.
        // Old daemons without the field default to "ok" for backward compatibility.
        const status = ev.status || (ev.text ? "ok" : "empty");
        clearWatchdog();
        if (status === "ok" && typeof ev.text === "string" && ev.text) {
          setNoteText(ev.text);
          const note = {
            id: ev.id || "n" + Date.now(),
            text: ev.text,
            createdAt: ev.createdAt || new Date().toISOString(),
            mode: ev.mode || captureModeRef.current,
            segments: normalizeSegments(ev.segments),
          };
          setCurrentNote(note);
          setHistory((entries) => [note, ...entries.filter((entry) => entry.id !== note.id)].slice(0, 50));
          setExpandedFrom("capture");
          setNoteView("expanded");
          toast(note.mode === "meeting" ? "Meeting saved to Dictations" : "Conversation note saved");
        } else if (status === "empty") {
          setNoteView(null);
          toast("No speech detected", { bad: true });
        } else if (status === "failed") {
          setNoteView(null);
          toast("Couldn't transcribe — try again", { bad: true });
        }
      }
      else if (ev.type === "transcript") {
        const eventId = Number.isInteger(ev.recording_id) ? ev.recording_id : null;
        if (eventId !== null && transcriptIdRef.current !== null && eventId < transcriptIdRef.current) {
          if (transcriptIdRef.current - eventId > TERMINAL_TRANSCRIPT_ID_LIMIT) resetTranscriptOrdering();
          else return;
        }
        if (eventId !== null && terminalTranscriptIdsRef.current.has(eventId) && ev.phase !== "final" && !ev.stale) return;
        if (eventId !== null) transcriptIdRef.current = eventId;
        if (eventId !== null && (ev.phase === "final" || ev.stale)) markTerminalTranscriptId(eventId);
        if (ev.stale) {
          // Belt-and-suspenders: _fail_recording_session fires a stale transcript
          // AND a note "failed" event. Resolve the view here (silent — the note
          // "failed" handler is the authoritative toaster to avoid a duplicate).
          // Old daemons without note "failed": UI unblocks but no toast; the 60 s
          // watchdog was also cleared here so it won't double-fire.
          if (noteViewRef.current === "processing") {
            clearWatchdog();
            setNoteView(null);
          }
          setTranscript({ phase: ev.phase || "final", text: "", stale: true });
        } else if (typeof ev.text === "string") {
          setTranscript({ phase: ev.phase || "partial", text: ev.text, stale: false });
        }
      } else if (ev.type === "provider-degraded") {
        // A fallback is a real persisted mode change, not a cosmetic degraded state.
        providerModeRef.current = "private";
        setProviderMode("private");
        setModelState(PRIVATE_MODEL);
        setProviderHealthy(true);
        setProviderDegraded(false);
        setProviderReason(ev.reason || null);
        setProviderActive("parakeet");
        ipc.patchConfig({ model: { backend: "parakeet", model: "parakeet-tdt-0.6b-v2" } })
          .catch(() => toast("Switched locally, but could not save the change", { bad: true }));
        triggerFlash("local");
        toast("Cloud failed — switched to on-device", { tone: "amber", icon: "cloudoff", ms: 6000 });
      } else if (ev.type === "provider-recovered") {
        // Ignore a late online probe after the fallback persisted Local.
        if (providerModeRef.current === "private") return;
        setProviderDegraded(false);
        setProviderActive(ev.active || "online");
        triggerFlash("remote");
        toast("Back online", { icon: "cloud" });
      } else if (ev.type === "sync-changed") {
        if (ev.sync) setSyncState(ev.sync);
      } else if (ev.type === "history-changed") {
        ipc.getState().then((st) => {
          if (!st) return;
          const entries = mapHistory(st);
          setHistory(entries);
          // Fallback: if still waiting for a "note" event, resolve from latest history.
          setNoteView((nv) => {
            if (nv === "processing" && entries.length > 0) {
              clearWatchdog();
              setCurrentNote(entries[0]);
              setExpandedFrom("capture");
              return "expanded";
            }
            return nv;
          });
        });
      }
    }, () => {
      // SSE reconnected (e.g. engine restarted after an update) — re-sync the
      // full state so history + quick-copy reflect anything missed while offline.
      ipc.getState().then((st) => { if (!cancelled && st) hydrate(st); }).catch(() => {});
    });
    return () => { cancelled = true; resetTranscriptOrdering(); clearWatchdog(); unsub && unsub(); };
  }, []);

  const resetTranscriptOrdering = () => {
    transcriptIdRef.current = null;
    terminalTranscriptIdsRef.current.clear();
    terminalTranscriptIdOrderRef.current = [];
  };

  const markTerminalTranscriptId = (id) => {
    const terminalIds = terminalTranscriptIdsRef.current;
    if (!terminalIds.has(id)) {
      terminalIds.add(id);
      terminalTranscriptIdOrderRef.current.push(id);
    }
    while (terminalTranscriptIdOrderRef.current.length > TERMINAL_TRANSCRIPT_ID_LIMIT) {
      const expired = terminalTranscriptIdOrderRef.current.shift();
      if (!terminalTranscriptIdOrderRef.current.includes(expired)) terminalIds.delete(expired);
    }
  };

  const hydrate = useCallback((st) => {
    if (st.model && st.model.id) setModelState(st.model.id);
    if (st.meetingModel && st.meetingModel.id) setMeetingModelState(st.meetingModel.id);
    if (st.meetingReadiness) setMeetingReadiness(st.meetingReadiness);
    if (st.shortcut) {
      if (Array.isArray(st.shortcut.display)) setShortcutState(st.shortcut.display);
      if (st.shortcut.activation) setActivationState(st.shortcut.activation);
    }
    if (Array.isArray(st.hotwords)) setHotwords(st.hotwords);
    setHistory(mapHistory(st));
    if (st.providers) {
      setKeys({
        openai: !!st.providers.openai?.configured,
        xai: !!st.providers.xai?.configured,
        gemini: !!st.providers.gemini?.configured,
      });
    }
    if (st.notes && typeof st.notes.recording === "boolean") setNoteRecording(st.notes.recording);
    if (st.notes && typeof st.notes.paused === "boolean") setNotePaused(st.notes.paused);
    if (st.notes && (st.notes.mode === "meeting" || st.notes.mode === "note")) setCaptureMode(st.notes.mode);
    if (st.notes && typeof st.notes.pauseReason === "string") setNotePauseReason(st.notes.pauseReason);
    else if (st.notes && !st.notes.paused) setNotePauseReason(null);
    if (st.prefs) {
      if (st.prefs.theme && st.prefs.theme !== "system") { explicitThemeRef.current = true; setThemeState(st.prefs.theme); }
      setTrayOnlyState(!!st.prefs.trayOnly);
      setOverlayState(!!st.prefs.overlay);
      setSoundState(!!st.prefs.sound);
      setAmbientState(!!st.prefs.ambient);
    }
    if (typeof st.startup === "boolean") setStartupState(st.startup);
    if (st.device?.device) setDevice2State(st.device.device);
    if (st.device?.compute) setComputeState(st.device.compute);
    if (st.version) setVersion(st.version);
    if (st.updateChannel) setUpdateChannel(st.updateChannel);
    if (typeof st.installedPackageVersion === "string") setInstalledPackageVersion(st.installedPackageVersion);
    if (st.providerHealth) {
      const ph = st.providerHealth;
      if (ph.mode === "online" && ph.degraded) {
        providerModeRef.current = "private";
        setProviderMode("private");
        setModelState(PRIVATE_MODEL);
        setProviderHealthy(true);
        setProviderDegraded(false);
        setProviderActive("parakeet");
        ipc.patchConfig({ model: { backend: "parakeet", model: "parakeet-tdt-0.6b-v2" } })
          .catch(() => {});
      } else {
        setProviderHealthy(!!ph.healthy);
        setProviderStatus(ph.status || "ok");
        setProviderMode(ph.mode || "private");
        setProviderDegraded(!!ph.degraded);
        if (ph.reason !== undefined) setProviderReason(ph.reason || null);
        if (ph.active) setProviderActive(ph.active);
      }
    }
    if (st.dictatePro) setDictatePro(st.dictatePro);
    if (st.productDestinations) setProductDestinations(st.productDestinations);
    if (typeof st.browserSigninEnabled === "boolean") setBrowserSigninEnabled(st.browserSigninEnabled);
    if (st.sync) setSyncState(st.sync);
  }, []);

  const mapHistory = (st) => mapHistoryPayload(st.history);

  // ---- toasts ----
  const dismiss = (id) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const toast = useCallback((msg, opts = {}) => {
    const id = "t" + Date.now() + Math.random();
    setToasts((ts) => [...ts, { id, msg, ...opts }]);
    const ms = opts.ms ?? (opts.undo ? 5000 : 2600);
    setTimeout(() => dismiss(id), ms);
  }, []);

  // ---- Note-surface watchdog (60 s safety net for missing terminal events) ----
  // clearWatchdog and armWatchdog are stable (useCallback with [] / [clearWatchdog,toast])
  // so the SSE useEffect can safely close over them even though it has [] deps.
  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) { clearTimeout(watchdogRef.current); watchdogRef.current = null; }
  }, []);
  const armWatchdog = useCallback(() => {
    clearWatchdog();
    watchdogRef.current = setTimeout(() => {
      watchdogRef.current = null;
      // Return to home only if we're still stuck in processing — never abort an expanded note.
      setNoteView((nv) => {
        if (nv === "processing") toast("Transcription timed out — try again", { bad: true });
        return nv === "processing" ? null : nv;
      });
    }, 60_000);
  }, [clearWatchdog, toast]);

  // ---- persisting mutations (optimistic local + IPC when live) ----
  const persist = (payload) => { if (ipc.isLive()) ipc.patchConfig(payload).catch(() => toast("Could not save change", { bad: true })); };
  const persistOrThrow = (payload) => ipc.isLive() ? ipc.patchConfig(payload) : Promise.resolve(null);

  const setModel = (id) => {
    setModelState(id);
    const m = modelById(id);
    // Optimistically update provider mode when the model changes.
    // Private (local) models are always healthy; switching clears any degraded state immediately.
    const newMode = m.local ? "private" : "online";
    setProviderMode(newMode);
    providerModeRef.current = newMode;
    if (m.local) { setProviderHealthy(true); setProviderDegraded(false); }
    persist({ model: { backend: m.backend, model: id.split("/").slice(1).join("/") } });
  };
  const setShortcut = async (arr) => {
    const previous = shortcut;
    setShortcutState(arr);
    try {
      await persistOrThrow({ shortcut: { combo: comboToToken(arr), activation } });
    } catch (e) {
      setShortcutState(previous);
      toast("Could not save change", { bad: true });
      throw e;
    }
  };
  const setActivation = (v) => { setActivationState(v); persist({ shortcut: { activation: v } }); };
  const setTheme = (v) => { explicitThemeRef.current = true; setThemeState(v); persist({ prefs: { theme: v } }); };
  const setStartup = (v) => { setStartupState(v); persist({ startup: v }); };
  const setTrayOnly = (v) => { setTrayOnlyState(v); persist({ prefs: { trayOnly: v } }); };
  const setOverlay = (v) => { setOverlayState(v); persist({ prefs: { overlay: v } }); };
  const setSound = (v) => { setSoundState(v); persist({ prefs: { sound: v } }); };
  const setAmbient = (v) => { setAmbientState(v); persist({ prefs: { ambient: v } }); };
  const setDevice2 = (v) => { setDevice2State(v); persist({ device: { device: v } }); };

  const addKey = (p) => setKeys((k) => ({ ...k, [p]: true }));
  const saveKey = (brand, key, modelId) => {
    if (ipc.isLive()) {
      ipc.saveApiKey(brand, key)
        .then(() => { addKey(brand); setModel(modelId); toast(`${providerLabel(brand)} key saved to keychain`); })
        .catch((e) => toast(e.message || "Could not save key", { bad: true }));
    } else {
      addKey(brand); setModel(modelId); toast(`${providerLabel(brand)} key saved to keychain`);
    }
  };

  const addHotword = (w) => {
    setHotwords((hw) => (hw.includes(w) ? hw : [...hw, w]));
    if (ipc.isLive()) ipc.addHotwords([w]).then((r) => r && setHotwords(r.hotwords)).catch(() => {});
  };
  const removeHotword = (w) => {
    setHotwords((hw) => hw.filter((x) => x !== w));
    if (ipc.isLive()) ipc.removeHotword(w).then((r) => r && setHotwords(r.hotwords)).catch(() => {});
  };

  const pushHistory = (text) =>
    setHistory((h) => [{ id: "h" + Date.now(), createdAt: new Date().toISOString(), text }, ...h].slice(0, 20));
  const clearHistory = () => {
    setHistory((prev) => {
      if (prev.length) toast("History cleared", { undo: () => setHistory(prev) });
      return [];
    });
    if (ipc.isLive()) ipc.clearHistory().catch(() => {});
  };

  const archiveNote = useCallback((note) => {
    if (!note?.id || leavingNoteIdsRef.current.has(note.id)) return;
    const index = history.findIndex((n) => n.id === note.id);
    if (index < 0) return;

    leavingNoteIdsRef.current.add(note.id);
    setLeavingNoteIds((ids) => (ids.includes(note.id) ? ids : [...ids, note.id]));

    archiveUndoRef.current.push({ note, index });
    if (archiveUndoRef.current.length > ARCHIVE_UNDO_LIMIT) archiveUndoRef.current.shift();

    const cancelRemoval = () => {
      const timer = archiveTimersRef.current.get(note.id);
      if (timer) {
        clearTimeout(timer);
        archiveTimersRef.current.delete(note.id);
      }
    };

    const restoreArchivedNote = () => {
      cancelRemoval();
      leavingNoteIdsRef.current.delete(note.id);
      setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
      setHistory((h) => {
        if (h.some((n) => n.id === note.id)) return h;
        const next = [...h];
        next.splice(Math.min(index, next.length), 0, note);
        return next;
      });
      archiveUndoRef.current = archiveUndoRef.current.filter((item) => item.note.id !== note.id);
      if (ipc.isLive()) {
        ipc.unarchiveHistoryItem(note.id).catch(() => {
          setHistory((h) => h.filter((n) => n.id !== note.id));
          toast("Could not restore note", { bad: true });
        });
      }
    };

    toast("Note archived", { undo: restoreArchivedNote });

    const timer = setTimeout(() => {
      archiveTimersRef.current.delete(note.id);
      leavingNoteIdsRef.current.delete(note.id);
      setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
      setHistory((h) => h.filter((n) => n.id !== note.id));
      if (currentNoteRef.current?.id === note.id) {
        setNoteView(null);
        setCurrentNote(null);
        setView(expandedFromRef.current === "history" ? "history" : "home");
      }
    }, ARCHIVE_LEAVE_MS);
    archiveTimersRef.current.set(note.id, timer);

    if (ipc.isLive()) {
      ipc.archiveHistoryItem(note.id).catch(() => {
        cancelRemoval();
        leavingNoteIdsRef.current.delete(note.id);
        setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
        archiveUndoRef.current = archiveUndoRef.current.filter((item) => item.note.id !== note.id);
        toast("Could not archive note", { bad: true });
      });
    }
  }, [history, toast]);

  const undoLastArchive = useCallback(() => {
    const stack = archiveUndoRef.current;
    if (!stack.length) return false;
    const { note, index } = stack[stack.length - 1];
    archiveUndoRef.current = stack.slice(0, -1);

    const timer = archiveTimersRef.current.get(note.id);
    if (timer) {
      clearTimeout(timer);
      archiveTimersRef.current.delete(note.id);
    }
    leavingNoteIdsRef.current.delete(note.id);
    setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
    setHistory((h) => {
      if (h.some((n) => n.id === note.id)) return h;
      const next = [...h];
      next.splice(Math.min(index, next.length), 0, note);
      return next;
    });
    if (ipc.isLive()) {
      ipc.unarchiveHistoryItem(note.id).catch(() => {
        setHistory((h) => h.filter((n) => n.id !== note.id));
        toast("Could not restore note", { bad: true });
      });
    }
    return true;
  }, [toast]);

  // triggerFlash: one-shot ring pulse on the cradle on every provider switch. Never silent.
  const triggerFlash = useCallback((to) => {
    const id = ++flashIdRef.current;
    setFlash({ to, id });
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => {
      setFlash((f) => (f && f.id === id ? null : f));
      flashTimerRef.current = null;
    }, 850);
  }, []);

  const hydrateProviderHealth = useCallback((ph) => {
    if (!ph) return;
    if (ph.mode === "online" && ph.degraded) {
      providerModeRef.current = "private";
      setProviderMode("private");
      setModelState(PRIVATE_MODEL);
      setProviderHealthy(true);
      setProviderDegraded(false);
      setProviderActive("parakeet");
      ipc.patchConfig({ model: { backend: "parakeet", model: "parakeet-tdt-0.6b-v2" } })
        .catch(() => toast("Switched locally, but could not save the change", { bad: true }));
      triggerFlash("local");
      toast("Cloud failed — switched to on-device", { tone: "amber", icon: "cloudoff", ms: 6000 });
      return;
    }
    setProviderHealthy(!!ph.healthy);
    setProviderStatus(ph.status || "ok");
    setProviderMode(ph.mode || "private");
    setProviderDegraded(!!ph.degraded);
    if (ph.reason !== undefined) setProviderReason(ph.reason || null);
    if (ph.active) setProviderActive(ph.active);
  }, [toast, triggerFlash]);

  const applyNoteState = (r) => {
    if (!r) return;
    if (typeof r.recording === "boolean") setNoteRecording(r.recording);
    if (typeof r.paused === "boolean") setNotePaused(r.paused);
    if (r.mode === "meeting" || r.mode === "note") setCaptureMode(r.mode);
    if (typeof r.pauseReason === "string") setNotePauseReason(r.pauseReason);
    else if (r.paused === false) setNotePauseReason(null);
  };

  const startNoteRecording = () => {
    if (noteRecording) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      clearWatchdog();
      setNotePaused(false);
      setNotePauseReason(null);
      setCaptureMode("note");
      setNoteRecording(true);
      setSessionStarted(true);
      setNoteView(null);
      setCurrentNote(null);
      toast("Note recording started");
      return;
    }
    ipc.startNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not start note recording", { bad: true }));
  };

  const startMeetingRecording = () => {
    if (noteRecording) return;
    if (meetingReadiness && meetingReadiness.ready === false) {
      toast(`Meeting model is not ready: ${meetingReadiness.reason || "prepare the local Meeting model first"}`, {
        bad: true,
        ms: 12_000,
      });
      return;
    }
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      clearWatchdog();
      setNotePaused(false);
      setNotePauseReason(null);
      setCaptureMode("meeting");
      setNoteRecording(true);
      setSessionStarted(true);
      setNoteView(null);
      setCurrentNote(null);
      toast("Meeting started");
      return;
    }
    setCaptureMode("meeting");
    ipc.startMeetingRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not start meeting", { bad: true }));
  };

  const pauseNoteRecording = () => {
    if (!noteRecording || notePaused) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      setNotePaused(true);
      return;
    }
    ipc.pauseNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not pause note recording", { bad: true }));
  };

  const resumeNoteRecording = () => {
    if (!noteRecording || !notePaused) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      setNotePaused(false);
      return;
    }
    ipc.resumeNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not resume note recording", { bad: true }));
  };

  const finishNoteRecording = () => {
    if (!noteRecording) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        setNotePaused(false);
        setNoteRecording(false);
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      setNotePaused(false);
      setNoteRecording(false);
      setNoteView("processing");
      armWatchdog();
      const demo = captureMode === "meeting"
        ? "Speaker 1: Let's capture the launch blockers.\nSpeaker 2: I will test the Windows build and report back tomorrow."
        : "Let's capture this as a project note. Add the follow-up action for tomorrow.";
      const demoSegments = captureMode === "meeting"
        ? [
            { seq: 0, tStart: 0, tEnd: 2.4, text: "Let's capture the launch blockers.", speakerLabel: "Speaker 1" },
            { seq: 1, tStart: 2.4, tEnd: 5.8, text: "I will test the Windows build and report back tomorrow.", speakerLabel: "Speaker 2" },
          ]
        : [];
      setTimeout(() => {
        clearWatchdog();
        const note = {
          id: "n" + Date.now(),
          text: demo,
          createdAt: new Date().toISOString(),
          mode: captureMode,
          segments: demoSegments,
        };
        setNoteText(demo);
        setCurrentNote(note);
        setHistory((entries) => [note, ...entries].slice(0, 50));
        setExpandedFrom("capture");
        setNoteView("expanded");
        toast(captureMode === "meeting" ? "Meeting saved to Dictations" : "Conversation note saved");
      }, 800);
      return;
    }
    const stop = captureMode === "meeting" ? ipc.stopMeetingRecording : ipc.stopNoteRecording;
    stop()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not finish recording", { bad: true }));
  };

  const discardNoteRecording = () => {
    if (!noteRecording) return;
    const reset = () => {
      setNoteRecording(false);
      setNotePaused(false);
      setNotePauseReason(null);
      setNoteView(null);
      setCurrentNote(null);
      setNoteElapsed(0);
      setTranscript({ phase: null, text: "", stale: false });
      clearWatchdog();
    };
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        reset();
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      reset();
      return;
    }
    discardPendingRef.current = true;
    const discard = captureMode === "meeting" ? ipc.discardMeetingRecording : ipc.discardNoteRecording;
    discard()
      .then((r) => {
        applyNoteState(r);
        reset();
      })
      .catch((e) => {
        discardPendingRef.current = false;
        toast(e.message || "Could not discard recording", { bad: true });
      });
  };

  const toggleNoteRecording = () => {
    if (!noteRecording) startNoteRecording();
    else if (notePaused) resumeNoteRecording();
    else finishNoteRecording();
  };

  const finishNoteRef = useRef(finishNoteRecording);
  finishNoteRef.current = finishNoteRecording;
  const noteRecRef = useRef(false); noteRecRef.current = noteRecording;
  const notePausedRef = useRef(false); notePausedRef.current = notePaused;

  const runDoctor = (cb) => {
    if (ipc.isLive()) { ipc.runDoctor().then(cb).catch(() => cb(mockDoctor())); }
    else cb(mockDoctor());
  };
  const checkUpdates = () => {
    setUpdateStatus((u) => ({ ...u, checking: true, error: null }));
    if (!ipc.isLive()) {
      const status = { ...mockUpdateStatus(version), checked: true, checking: false };
      setUpdateStatus(status);
      toast("You're on the latest version");
      return;
    }
    ipc.checkUpdates()
      .then((status) => {
        const next = { ...(status || {}), checking: false };
        setUpdateStatus(next);
        if (next.installKind === "windows-store") {
          setUpdateChannel("stable");
          toast("Checking for updates in Microsoft Store");
          startUpdate();
          return;
        }
        if (next.updateAvailable && next.latestVersion) toast(`Dictate ${next.latestVersion} is available`);
        else if (next.checked) toast("You're on the latest version");
        else toast("Could not check for updates", { bad: true });
      })
      .catch((e) => {
        setUpdateStatus((u) => ({ ...u, checked: false, checking: false, error: e.message || "Could not check for updates" }));
        toast("Could not check for updates", { bad: true });
      });
  };
  const startUpdate = () => {
    setUpdateStatus((u) => ({ ...u, updating: true, error: null }));
    setUpdateErrorReason(null);
    if (!ipc.isLive()) {
      window.open("https://github.com/arcforgelabs/dictate/releases", "_blank", "noopener,noreferrer");
      setUpdateStatus((u) => ({ ...u, updating: false }));
      toast("Opened latest release");
      return;
    }
    ipc.startUpdate()
      .then((flow) => {
        setUpdateStatus((u) => ({ ...u, updating: false }));
        if (flow?.mode === "installed" || (flow?.actions || []).includes("restart")) {
          requestUpdateRestart(flow?.message || "Update installed — restarting…");
          return;
        }
        if (flow?.mode === "error" || flow?.phase === "failed") {
          const detail = flow.errorDetail || flow.message || "Could not complete the update";
          setUpdateStatus((u) => ({ ...u, error: detail }));
          setUpdatePhase("error");
          setUpdateErrorReason(detail);
          toast(flow?.message || "Could not complete the update", { bad: true });
          return;
        }
        if (flow?.mode === "busy") {
          applyPolledUpdateStatus(flow);
          startUpdatePolling(flow?.installKind === "linux-package" ? "package" : "command");
          return;
        }
        if (flow?.started && flow?.installKind === "linux-package") {
          applyPolledUpdateStatus(flow);
          startUpdatePolling("package");
          return;
        }
        if (flow?.mode === "command" && flow?.started) {
          setUpdatePhase("working");
          setUpdateProgress(null);
          startUpdatePolling("command");
        } else {
          setUpdatePhase(flow?.started ? "available" : "idle");
        }
        if (flow?.url) {
          window.open(flow.url, "_blank", "noopener,noreferrer");
        }
        if (flow?.started) toast(flow?.message || "Update started");
        else toast(flow?.message || "Opened latest release");
      })
      .catch((e) => {
        setUpdateStatus((u) => ({ ...u, updating: false, error: e.message || "Could not start update" }));
        setUpdatePhase("error");
        setUpdateErrorReason(e.message || "Could not start update");
        toast("Could not start update", { bad: true });
      });
  };
  const mockDoctor = () => ({
    ok: true,
    checks: [
      { label: "Microphone access", sub: "Default device responding", ok: true },
      { label: "Model loads", sub: modelById(model).name, ok: true },
      { label: "Output backend", sub: "Typing into focused app", ok: true },
      { label: "Secret store", sub: "the desktop Secret Service keyring", ok: true },
      { label: "Shortcut registered", sub: shortcut.join(" + "), ok: true },
    ],
  });

  function mockUpdateStatus(v) {
    // Shell + engine are one unit at one version — no separate component tracking.
    return {
      currentVersion: v, latestVersion: v, updateAvailable: false, checked: false,
      platform: "linux", installKind: "linux-package",
      phase: "current", actions: ["check", "open_docs"],
      commands: { release: "https://github.com/arcforgelabs/dictate/releases" },
    };
  }

  // ---- update affordance: skip / dismiss / run ----
  // Skip = suppress until a newer version (persisted). Dismiss = until next launch (session).
  const skipUpdate = () => {
    const v = updateStatus.latestVersion;
    if (v) { setSkippedVersion(v); try { localStorage.setItem("dictate.skippedVersion", v); } catch { /* ignore */ } }
    stopUpdatePolling();
    setUpdatePhase("idle");
    setUpdateProgress(null);
    setUpdateErrorReason(null);
    toast("Skipped this version");
  };
  const dismissUpdate = () => { setUpdateDismissed(true); };
  const runUpdate = () => {
    if (updatePhase === "downloading" || updatePhase === "verifying" || updatePhase === "installing" || updatePhase === "working") return;
    if (updatePhase === "restart" || updatePhase === "restarting") {
      requestUpdateRestart("Restarting Dictate…");
      return;
    }
    if (!ipc.isLive()) {
      setUpdatePhase("working");
      setTimeout(() => {
        toast("Updated — restarting…");
        setUpdateDismissed(true);
        setUpdatePhase("idle");
        setUpdateProgress(null);
      }, 1600);
      return;
    }
    setUpdateProgress(null);
    setUpdateInstallStartedAt(null);
    setUpdateInstallElapsed(null);
    setUpdateErrorReason(null);
    startUpdate();
  };

  // ---- launch-time update flow: silent check, prepare in the background ----
  useEffect(() => {
    if (!ipc.isLive()) {
      const t1 = setTimeout(() => {
        setUpdateStatus((u) => ({ ...u, updateAvailable: true, latestVersion: "2026.7.1", checked: true }));
        setUpdatePhase((p) => (p === "idle" ? "available" : p));
      }, 900);
      return () => { clearTimeout(t1); };
    }
    let cancelled = false;
    ipc.checkUpdates().then((st) => {
      if (cancelled || !st) return;
      setUpdateStatus((u) => ({ ...u, ...st }));
      if (st.installKind === "windows-store") setUpdateChannel("stable");
      const mapped = mapBackendUpdatePhase(st);
      if (mapped === "error") {
        setUpdatePhase("error");
        setUpdateErrorReason(st.errorDetail || st.error || "Update failed");
        return;
      }
      if (mapped === "downloading" || mapped === "verifying" || mapped === "installing") {
        applyPolledUpdateStatus(st);
        startUpdatePolling("package");
        return;
      }
      if (mapped === "restart") {
        setUpdatePhase("restart");
        return;
      }
      if (!st.updateAvailable) return;
      setUpdatePhase("available");
    }).catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- dictation demo (mock mode only; live mode is driven by SSE) ----
  const typeText = (phrase) => {
    setTyping(true);
    const prefix = tgtRef.current ? tgtRef.current.trim() + " " : "";
    let i = 0;
    const id = setInterval(() => {
      i++;
      setTargetText(prefix + phrase.slice(0, i));
      if (i >= phrase.length) {
        clearInterval(id); setTyping(false);
        pushHistory(phrase); toast("Inserted into Notes");
      }
    }, 16);
  };
  const dictateStart = () => { if (recRef.current || live) return; setRecording(true); setSessionStarted(true); };
  const dictateStop = () => {
    if (!recRef.current || live) return;
    setRecording(false);
    const phrase = DEMO_PHRASES[Math.floor(Math.random() * DEMO_PHRASES.length)];
    setTimeout(() => typeText(phrase), 220);
  };
  const dictateOnce = () => { if (recRef.current || live) return; setRecording(true); setTimeout(dictateStop, 1300); };

  // ---- global keyboard: ⌘K palette + push-to-talk demo (Right Ctrl) ----
  useEffect(() => {
    const down = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        if (!archiveUndoRef.current.length) return;
        e.preventDefault();
        undoLastArchive();
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (e.code === "ControlRight" && !e.repeat) {
        if (live && noteRecRef.current && !notePausedRef.current && actRef.current === "hold") {
          e.preventDefault();
          finishNoteRef.current();
          return;
        }
        if (capRef.current || live) return;
        e.preventDefault();
        if (actRef.current === "toggle") { recRef.current ? dictateStop() : dictateStart(); }
        else dictateStart();
        return;
      }
      if (capRef.current || live) return;
    };
    const up = (e) => {
      if (capRef.current || live) return;
      if (e.code === "ControlRight" && actRef.current === "hold") { e.preventDefault(); dictateStop(); }
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    return () => { window.removeEventListener("keydown", down, true); window.removeEventListener("keyup", up, true); };
  }, [live, undoLastArchive]);

  // ---- fit-to-viewport scaler (a real 1100×768 Tauri window stays at 1.0) ----
  const winRef = useRef(null);
  useEffect(() => {
    const fit = () => {
      const el = winRef.current; if (!el) return;
      const pad = 32, W = 1100, H = 768;
      const sc = Math.min(1, (window.innerWidth - pad) / W, (window.innerHeight - pad) / H);
      el.style.transform = `translate(-50%, -50%) scale(${sc})`;
    };
    fit(); window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  // The pill shows while an update exists or while a completed update is waiting
  // for a clean shell+engine restart.
  const updateVisible = updatePhase !== "idle" && !updateDismissed
    && (
      !!updateStatus.updateAvailable
      || updatePhase === "restart"
      || updatePhase === "restarting"
      || updatePhase === "error"
      || updatePhase === "downloading"
      || updatePhase === "verifying"
      || updatePhase === "installing"
      || updatePhase === "working"
    )
    && (!skippedVersion || updateStatus.latestVersion !== skippedVersion);

  const store = {
    view, setView, model, setModel, keys, addKey, saveKey, shortcut, setShortcut, activation, setActivation,
    device, device2, setDevice2, compute, hotwords, addHotword, removeHotword,
    history, clearHistory, archiveNote, leavingNoteIds, theme, setTheme, startup, setStartup, trayOnly, setTrayOnly,
    overlay, setOverlay, sound, setSound, ambient, setAmbient,
    recording, noteRecording, sessionStarted, notePaused, notePauseReason, captureMode, noteText,
    startNoteRecording, startMeetingRecording, pauseNoteRecording, resumeNoteRecording,
    finishNoteRecording, discardNoteRecording, toggleNoteRecording,
    transcript, typing, targetText, dictateStart, dictateStop, dictateOnce,
    palette, setPalette, toasts, toast, dismiss, micConnected: true, setCapturing,
    runDoctor, version, updateChannel, setUpdateChannel, installedPackageVersion, setInstalledPackageVersion, updateStatus, checkUpdates, startUpdate, platform,
    // Update affordance
    updatePhase, updateProgress, updateInstallElapsed, updateErrorReason, updateVisible, runUpdate, skipUpdate, dismissUpdate,
    // Note Capture additions
    noteElapsed, reduced, audioLevel, live,
    noteView, setNoteView, currentNote, setCurrentNote,
    expandedFrom, setExpandedFrom,
    // Provider health — on-device is always available; degraded = fell back from the online provider
    providerHealthy, providerStatus, providerMode,
    providerDegraded, providerReason, providerActive,
    flash, hydrateProviderHealth, meetingModel,
    meetingReadiness,
    dictatePro, setDictatePro, productDestinations, browserSigninEnabled, syncState, setSyncState, syncBusy, setSyncBusy,
    accountOpen, setAccountOpen, setHistory,
  };

  // Resolve the current settings view component (null when on capture home).
  const Current = view !== "home" ? VIEWS[view] : null;
  const nativeDecorations = typeof document !== "undefined"
    && document.documentElement.getAttribute("data-native-decorations") === "true";
  const nativeChrome = nativeDecorations || platform === "win11" || platform === "win10";

  return (
    <StoreCtx.Provider value={store}>
      <div className={"win " + platform + (nativeChrome ? " native-chrome" : "")} ref={winRef}>
        {!nativeChrome && (
          <TitleBar
            platform={platform}
            hasUpdate={!!updateStatus.updateAvailable}
          />
        )}

        <div className="shell">
          {view === "home" ? (
            noteView === "processing" ? <NoteProcessing /> :
            noteView === "expanded"   ? <ExpandedNote /> :
            <CaptureHome />
          ) : (
            /* The only non-home view is the Notes list — it renders its own header. */
            <div className="note-settings-wrap">
              {Current && <Current />}
            </div>
          )}
        </div>

        <ListeningHUD />
        <CommandPalette />
        {accountOpen && <AccountDialog />}
        <Toasts />
      </div>
    </StoreCtx.Provider>
  );
}

function providerLabel(brand) {
  return { openai: "OpenAI", xai: "xAI", gemini: "Gemini" }[brand] || brand;
}

// Display keys (["Ctrl","Shift","R"] / ["Ctrl (R)"]) → engine combo token.
function comboToToken(arr) {
  const map = { "Ctrl": "ctrl", "Ctrl (R)": "ctrl_r", "Right Ctrl": "ctrl_r", "Ctrl (L)": "ctrl_l",
    "Alt": "alt", "Shift": "shift", "Super": "super", "D": "d" };
  return arr.map((k) => map[k] || k.toLowerCase()).join("+");
}
