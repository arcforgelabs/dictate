# Dictate Desktop Browser Sign-In — Architecture

> **Authority:** Subordinate to [goal.md](goal.md). Proposed sign-in design input;
> production auth durability and return-path truth follow Wave 1 forge implementation
> and [forge-wave4-release-readiness-2026-07-12.md](forge-wave4-release-readiness-2026-07-12.md).

**Status:** Proposed · **Scope:** Arc Forge gateway (`https://console.arcforge.au`) + Dictate desktop client (`src/dictate/pro/client.py`, `src/dictate/ui_server.py`, `ui/src`)

## Decision summary

| Decision | Choice |
|---|---|
| Primary flow | **Authorization Code + PKCE (S256) with loopback redirect** — RFC 8252 §7.3 (`http://127.0.0.1:<ephemeral>/callback`) |
| Fallback #1 | **Device Authorization Grant** — RFC 8628 (user code at `/deck/link`) — auto-selected when a loopback callback can't work |
| Fallback #2 | **Email code** (existing `login-code`/`verify-code`) — retained unchanged, terminal fallback |
| Token system | **Reuse existing JWT access/refresh issuance.** All new grants terminate in the *existing* `POST /api/account/auth/token` response shape `{access_token, refresh_token, expires_in}`. No parallel token system. |
| Client identity | Static public client `client_id=dictate-desktop`, **no client secret** (impossible to keep one in a distributed native binary) |
| Capability detection | Probe + 404/405/501 degradation, mirroring signed-upload and device-registration patterns already in `client.py` |
| Legacy `/v1` mode | Browser flows are **gateway-only** for v1; legacy/localhost mode (`_uses_arcforge_gateway() == False`) keeps email-code only |

### Why loopback+PKCE primary, device grant fallback

- **Loopback wins on UX when browser and app share a machine** (the overwhelmingly common case for a desktop dictation app): zero typing, sub-second completion, no code to transcribe. RFC 8252 names it the recommended pattern for native apps.
- **Loopback fails structurally when the browser is elsewhere**: SSH sessions, the UI viewed through a port-forward, kiosk/locked-down firewalls that block even ephemeral loopback listeners. In those cases the redirect to `127.0.0.1:<port>` resolves on the *wrong machine* (or nowhere). The device grant has no callback at all — the desktop *polls out* — so it works over SSH, behind any egress-only firewall, and when the user approves on their phone.
- **Windows quirks:** binding `127.0.0.1:0` does not trigger the Windows Firewall consent dialog (that fires on non-loopback binds), and the app already runs a localhost UI server, so loopback binding is proven viable in the field. The one real Windows risk — another local process racing to bind — is mitigated because we bind an *ephemeral* port *before* constructing the authorize URL (see Security).
- **Neither flow can use a client secret**, so PKCE is mandatory for the code flow, and the device grant is inherently secret-free. Email code remains the floor because it requires nothing but SMTP and works when the gateway hasn't shipped the new endpoints yet.

**Selection rule (client-side):** try loopback if (a) gateway advertises it, (b) we can bind `127.0.0.1:0`, and (c) we can plausibly open/display a local browser. Otherwise device grant if advertised. Otherwise email code. The UI also offers "Use a code instead" to jump down the ladder manually.

## Sequence of events (primary flow)

```
 Dictate UI          UI server            ProClient              System            Gateway
 (React, in         (localhost,          (browser_auth)          browser        console.arcforge.au
  browser/webview)   ui_server.py)
     |                   |                     |                    |                  |
 [1] |--POST /api/pro/auth/browser/start----->|                    |                  |
     |                   |--start_browser_sign_in()                |                  |
     |                   |   gen code_verifier, state              |                  |
     |                   |   bind 127.0.0.1:0  -> port P           |                  |
     |                   |   listener waits (single GET, 300s TTL) |                  |
     |                   |<--{authorize_url, flow:"loopback"}      |                  |
 [2] |<--200 {flow, authorizeUrl}             |                    |                  |
     |                   |------------- webbrowser.open(url) ----->|                  |
 [3] |                   |                     |                    |--GET /api/account/auth/authorize
     |                   |                     |                    |   ?client_id=dictate-desktop
     |                   |                     |                    |   &redirect_uri=http://127.0.0.1:P/callback
     |                   |                     |                    |   &state=S&code_challenge=C&...
     |                   |                     |                    |                  |
 [4] |                   |                     |                    |  (no /deck session?) 302 -> /deck/login?next=...
     |                   |                     |                    |  user signs in to portal
 [5] |                   |                     |                    |  consent page: "Approve sign-in
     |                   |                     |                    |   for Dictate on this computer?"
     |                   |                     |                    |  user clicks Approve
 [6] |                   |                     |                    |<-302 http://127.0.0.1:P/callback?code=AC&state=S
     |                   |                     |<--GET /callback?code=AC&state=S       |
     |                   |                     |   verify state==S; show "You're      |
     |                   |                     |   signed in" page; close listener    |
 [7] |                   |                     |--POST /api/account/auth/token------->|
     |                   |                     |   {grant_type:"authorization_code",  |
     |                   |                     |    code:AC, code_verifier,           |
     |                   |                     |    redirect_uri, client_id}          |
     |                   |                     |<--{access_token, refresh_token,      |
     |                   |                     |    expires_in}                       |
 [8] |                   |                     |--POST /api/dictate/devices/register->|
     |                   |                     |   {device_id, device_label,          |
     |                   |                     |    device_public_key}   (Bearer)     |
     |                   |                     |  save_session() -> keyring + json    |
 [9] |--GET /api/pro/auth/browser/status----->|                    |                  |
     |<--{status:"complete", dictatePro:{...}}|                    |                  |
```

Steps 1–2 are synchronous; 3–8 happen while the UI polls step 9 (1s interval, matching existing update-status polling style).

## 1. Flow choice (detail)

Covered in the decision summary. One addition on **remote-UI detection**: the UI server can't reliably know the viewer's browser is remote, so we don't guess — the loopback attempt self-diagnoses. If the listener times out (300s) with no callback, the UI offers "Having trouble? Use a code instead", which triggers the device grant (or email code). Users who *know* they're remote can click it immediately. Additionally, `POST /api/pro/auth/browser/start` accepts `{"flow": "device_code"}` to force the fallback; the React UI passes it when `window.location.hostname` is not `127.0.0.1`/`localhost` (a cheap, correct-enough remote heuristic).

## 2. Server-side contract (new gateway endpoints)

All under the existing gateway namespace. Registered public client: `client_id = dictate-desktop`, allowed scopes `dictate` (implies today's access set), redirect pattern below. No secret.

### 2.1 `GET /api/account/auth/desktop` — capability discovery

Cheap unauthenticated probe (client mirrors its 404/405/501 pattern; a 404 here means "email code only").

```json
200 {
  "authorization_endpoint": "https://console.arcforge.au/api/account/auth/authorize",
  "token_endpoint": "https://console.arcforge.au/api/account/auth/token",
  "device_authorization_endpoint": "https://console.arcforge.au/api/account/auth/device-code",
  "grant_types_supported": ["authorization_code", "urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"]
}
```

(Deliberately shaped like a subset of OIDC discovery so `/.well-known/openid-configuration` can alias it later — open question 7.5.)

### 2.2 `GET /api/account/auth/authorize` — browser-navigated authorization

Query parameters (all required unless noted):

| Param | Value / validation |
|---|---|
| `response_type` | must be `code` |
| `client_id` | must be `dictate-desktop` |
| `redirect_uri` | must match `http://127.0.0.1:{1024-65535}/callback` or `http://[::1]:{port}/callback` **exactly** (scheme http, host literal `127.0.0.1` or `[::1]` — reject `localhost` per RFC 8252 §8.3; path exactly `/callback`; no query/fragment). Port is free per RFC 8252 §7.3. |
| `state` | 1–512 chars, opaque, round-tripped verbatim |
| `code_challenge` | 43–128 chars base64url |
| `code_challenge_method` | must be `S256` (reject `plain`) |
| `scope` | optional, default `dictate` |
| `device_label` | optional, ≤ 64 chars, shown on the consent page ("Dictate on samuel-laptop") |

Behavior:
1. **No portal session** → 302 to `/deck/login?next=<urlencoded original authorize URL>`. After login the portal redirects back; the authorize handler re-evaluates.
2. **Portal session present** → render a consent page (server-side, inside `/deck` chrome): account email, "A desktop app on this computer is requesting sign-in", device label if given, **Approve / Deny** buttons. Approval must be a `POST` with the portal's CSRF token (never auto-approve on GET — see Security 5.3).
3. **Approve** → mint authorization code, 302 to `redirect_uri?code=<AC>&state=<state>`.
4. **Deny** → 302 to `redirect_uri?error=access_denied&state=<state>`.
5. Validation failure of `redirect_uri`/`client_id` → render an error page, **never redirect** (avoid open-redirect). Other param errors → redirect with `error=invalid_request&state=...`.

**Authorization code properties:** ≥ 128 bits entropy; stored server-side **hashed (SHA-256)** with `{account_id, client_id, redirect_uri, code_challenge, scope, created_at}`; TTL **120 s**; single-use. Reuse of a consumed code → `invalid_grant` **and revoke all tokens previously issued from that code** (RFC 6749 §4.1.2 replay defense).

### 2.3 `POST /api/account/auth/token` — extended (existing endpoint, new grant types)

Today it handles `grant_type=refresh_token`. Add:

**a) `authorization_code`:**
```json
{ "grant_type": "authorization_code", "code": "...", "code_verifier": "...",
  "redirect_uri": "http://127.0.0.1:P/callback", "client_id": "dictate-desktop" }
```
Server: look up hashed code; check TTL, single-use, `client_id` + `redirect_uri` exact match, and `BASE64URL(SHA256(code_verifier)) == code_challenge`. Success →

```json
200 { "access_token": "<JWT, sub=account_id>", "refresh_token": "...", "expires_in": 3600, "token_type": "Bearer" }
```
— byte-identical shape to today's `verify-code` response, so `_session_from_arcforge_auth_response` works unmodified.

**b) `urn:ietf:params:oauth:grant-type:device_code`:**
```json
{ "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": "...", "client_id": "dictate-desktop" }
```
Responses per RFC 8628 §3.5: `400 {"error":"authorization_pending"}` while waiting; `400 {"error":"slow_down"}` (client adds 5 s to interval); `400 {"error":"expired_token"}`; `400 {"error":"access_denied"}`; success → same token payload as (a).

**Errors (both grants):** `400 invalid_request` (malformed), `400 invalid_grant` (bad/expired/replayed code, PKCE mismatch, redirect mismatch), `400 unauthorized_client` (unknown client_id), `429` with `Retry-After` (rate limit).

**Token lifetimes:** access JWT `expires_in = 3600` (unchanged); refresh token 30 days (matches the client's existing `refresh_expires_at` assumption at `client.py:500`), **rotated on every refresh** with a 60 s grace window for the just-superseded token (network-retry safety); reuse outside grace revokes the whole token family.

### 2.4 `POST /api/account/auth/device-code` — device authorization (fallback)

Request: `{ "client_id": "dictate-desktop", "scope": "dictate", "device_label": "Dictate on samuel-laptop" }`

```json
200 {
  "device_code": "<256-bit opaque>",
  "user_code": "BDWP-HQZM",
  "verification_uri": "https://console.arcforge.au/deck/link",
  "verification_uri_complete": "https://console.arcforge.au/deck/link?code=BDWP-HQZM",
  "expires_in": 900,
  "interval": 5
}
```
`user_code`: 8 chars from a confusion-free alphabet (`BCDFGHJKLMNPQRSTVWXZ`), hyphenated, ~4×10^10 space; rate-limit entry attempts (5/min per portal session, lockout after 10 bad codes per code). `/deck/link` requires a portal session (redirects through `/deck/login` otherwise), shows the same consent copy as 2.2 step 2 plus the device label, Approve/Deny via CSRF-protected POST.

### 2.5 Tie-in to existing endpoints

- `POST /api/dictate/devices/register` — **unchanged**. The desktop calls it with the new access token immediately after token exchange, exactly as `complete_sign_in` does today (`_register_gateway_device`, including its 404/405/501 tolerance).
- `POST /api/account/auth/login-code` + `verify-code` — unchanged, remain the email fallback.
- The consent approval is recorded as an auth event on the account (visible in the portal's session/device list) so users can audit "Desktop sign-in approved from IP … at …".

## 3. Client-side design

### 3.1 New module: `src/dictate/pro/browser_auth.py`

```python
@dataclass(slots=True)
class BrowserAuthAttempt:
    flow: str                    # "loopback" | "device_code"
    state: str                   # loopback only
    code_verifier: str           # loopback only
    redirect_uri: str            # loopback only
    authorize_url: str           # loopback only
    device_code: str             # device flow only
    user_code: str               # device flow only
    verification_uri: str
    interval: int
    expires_at: datetime
```

**`LoopbackListener`** (stdlib `http.server` on a daemon thread, matching the codebase's no-new-deps style):
- Bind `socket.bind(("127.0.0.1", 0))` → learn port → construct `redirect_uri`. Bind **before** the authorize URL exists (anti-race, §5.2).
- Serve exactly one `GET /callback`: if `state` mismatch or `error` param → record failure; else record `code`. Respond with a self-contained ~1 KB HTML page: "Signed in. You can close this tab and return to Dictate." (No tokens, no code echoed back into the page.) All other paths → 404. `Connection: close`.
- Hard deadline 300 s via `socket.settimeout` + monotonic check; `close()` is idempotent and called on success, timeout, cancel, new attempt, and UI-server shutdown.
- One attempt at a time: starting a new attempt closes the previous listener (`ProClient` holds `self._browser_attempt`).

### 3.2 `ProClient` additions (`src/dictate/pro/client.py`)

```python
def desktop_auth_capabilities(self) -> dict | None:
    # GET /api/account/auth/desktop; ProClientError 404/405/501 -> None (cache for process lifetime)

def start_browser_sign_in(self, *, device_label: str = "Desktop", prefer: str = "auto") -> dict:
    # gateway-only: if not self._uses_arcforge_gateway() -> ProClientError(501, ...)
    # caps = self.desktop_auth_capabilities(); pick loopback -> device_code -> raise 501 ("email")
    # loopback: verifier = secrets.token_urlsafe(64)[:128]; challenge = S256(verifier)
    #           state = secrets.token_urlsafe(32); bind listener; build authorize_url
    # returns {"flow": "loopback", "authorize_url": ..., "expires_in": 300}
    #      or {"flow": "device_code", "user_code": ..., "verification_uri": ..., "expires_in": 900, "interval": 5}

def poll_browser_sign_in(self, *, device_public_key: str | None = None,
                         device_label: str = "Desktop") -> dict:
    # loopback: non-blocking check of listener result
    #   pending -> {"status": "pending"}; timeout/denied/state-mismatch -> {"status": "error", "reason": ...}
    #   code -> POST token(grant_type=authorization_code, code, code_verifier, redirect_uri, client_id)
    # device_code: if >= interval since last poll -> POST token(device_code grant)
    #   authorization_pending -> pending; slow_down -> interval += 5; expired/denied -> error
    # on tokens (either flow):
    #   session = self._session_from_arcforge_auth_response(response)   # unchanged reuse
    #   if device_public_key: session = self._register_gateway_device(session, ...)  # unchanged reuse
    #   self.save_session(session)                                       # unchanged reuse (keyring path)
    #   return {"status": "complete", "account_id": ..., "device_id": ...}

def cancel_browser_sign_in(self) -> None:
```

`account_id` continues to come from `_jwt_subject(access_token)`; `device_id` defaults to `"dictate-desktop"` until `devices/register` returns the canonical one — identical to the email-code path today.

### 3.3 UI-server backend + routes (`src/dictate/ui_server.py`)

Backend methods (beside `start_pro_sign_in` / `complete_pro_sign_in`):

- `start_pro_browser_sign_in(flow="auto")`: generates the device key pair **up front** via `generate_device_key_pair()` and stashes it on the pending attempt; calls `client.start_browser_sign_in(device_label=<hostname>)`; if flow is `loopback`, calls `webbrowser.open(authorize_url)` (best-effort; the URL is also returned so the UI renders a clickable "Open sign-in page" link — covers webview/no-default-browser cases); on `ProClientError(501/404/405)` returns `{"flow": "email"}` so the UI drops to the existing email-code form.
- `poll_pro_browser_sign_in()`: delegates to `client.poll_browser_sign_in(device_public_key=..., device_label=...)`; on `"complete"`, persists the private key via `api_keys_mod.save_sync_device_private_key(session.device_id, ...)` (same code as today's `complete_pro_sign_in`) and returns `{"status": "complete", "signedIn": True, "dictatePro": client.get_state()}`.
- `cancel_pro_browser_sign_in()`.

Routes (same dispatch style as the existing `/api/pro/auth/*` block at ~line 1794):
```
POST /api/pro/auth/browser/start    {flow?: "auto"|"loopback"|"device_code"}
GET  /api/pro/auth/browser/status
POST /api/pro/auth/browser/cancel
```

### 3.4 Fallback ladder (normative)

1. Loopback code+PKCE — gateway advertises `authorization_code` AND local bind succeeds AND flow not forced to `device_code`.
2. Device grant — gateway advertises it; also reachable manually via "Use a code instead" while a loopback attempt is pending.
3. Email code — capabilities probe 404s, both flows unavailable, or user picks "Email me a code". Existing endpoints/UI unchanged. Legacy `/v1` (localhost) mode goes straight here.

## 4. UI/UX (account panel, `ui/src/App.jsx`)

Replaces the current signed-out block ("Browser sign-in unavailable" + portal link, App.jsx:590–603). One account row, no provider/brand names, house style intact.

**Signed out (idle):** one primary button **"Sign in"** with a one-line consent note beneath: *"Opens your browser to connect this device to your account."* Secondary text-link: *"Email me a code instead"* → existing email-code form.

**Waiting (loopback):** button → disabled **"Waiting for browser…"** with the existing spinner treatment; below: *"Approve the sign-in in the browser tab we just opened."* + text links **"Open sign-in page"** (re-fires `authorize_url` — covers popup blockers/remote UI) · **"Use a code instead"** · **"Cancel"**. UI polls `/api/pro/auth/browser/status` every 1 s.

**Waiting (device grant):** show the code large and copyable — `BDWP-HQZM` — with *"Enter this code at your account portal"* and an **"Open portal"** button (`verification_uri_complete`). Same Cancel/poll behavior. (Portal referred to generically, matching the existing "Account portal" wording.)

**Timeout / denied / error:** inline notice in the `account-consent` block — *"Sign-in timed out."* / *"Sign-in was declined."* / *"Couldn't reach the sign-in service."* — with **"Try again"** and **"Email me a code"**. Never a modal, never a red full-block (graceful-degradation house rule).

**Success:** the poll returns `dictatePro` state; the store swaps to the signed-in rows (Plan, sync enable, etc.) exactly as the email-code path does today. No success interstitial in-app; the browser tab shows the "you can close this tab" page.

`store.jsx` gains `startBrowserSignIn()`, `pollBrowserSignIn()` (interval, cleared on unmount/success/cancel), `cancelBrowserSignIn()`, and a `browserSignIn: {status, flow, userCode?, verificationUri?, authorizeUrl?, error?}` slice.

## 5. Security analysis

1. **PKCE is mandatory, not optional.** `dictate-desktop` is a public client: any secret shipped in the pip/npm artifact is public. S256 ensures a stolen authorization code (log leak, redirect interception) is worthless without the in-memory `code_verifier`, which never leaves the desktop process except over TLS to the token endpoint. `plain` is rejected server-side.
2. **Loopback interception.** Threat: local malware binds a port and lures the redirect. Mitigations: (a) client binds the ephemeral port *before* the authorize URL exists, so the URL always names a port we own; (b) even a stolen code fails PKCE; (c) redirect host restricted to `127.0.0.1`/`[::1]` literals — `localhost` rejected (resolver hijack, RFC 8252 §8.3); (d) codes are 120 s single-use. Residual: same-user local malware can do worse than steal auth codes; out of scope.
3. **`state` / CSRF, both directions.** Client rejects any callback whose `state` mismatches (blocks session-fixation: attacker can't splice *their* code into the victim's listener). Portal-side approval is a POST guarded by the `/deck` CSRF token, and consent is never granted on bare GET — blocks drive-by `<img src=…/authorize…>` auto-approval.
4. **Code replay.** Hashed-at-rest, single-use, 120 s TTL; consumed-code reuse revokes the token family it minted.
5. **Token storage.** Unchanged, deliberately: refresh token → OS keyring via `save_pro_refresh_token`, plaintext only behind `DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS=1`; session metadata → `pro-session.json` chmod 600. Browser flow feeds the identical `save_session` path; `code_verifier`/`state` are memory-only and discarded after exchange.
6. **Refresh rotation.** Server rotates on every refresh (60 s grace); client already persists the returned refresh token on refresh, so no client change. Reuse-outside-grace → family revocation → client's existing `get_state` failure path clears the session and shows signed-out.
7. **Binding tokens to the device public key (assessed, deferred).** Full proof-of-possession (DPoP-style x25519→Ed25519 signing of token requests) touches every authenticated call and drags `signing.py` into the auth path — poor cost/benefit for v1. **v1 compromise:** token exchange accepts optional `device_public_key`; gateway records the fingerprint against the refresh-token family, so portal revocation of a device (`devices/{id}/revoke`) can also kill that family's refresh tokens. Full PoP is open question 7.4.
8. **Device-grant specifics.** Confusion-free 8-char user code, entry rate-limited, 15 min TTL, consent page shows the device label so the user notices unexpected pairing requests; `verification_uri_complete` still requires an explicit Approve click (no code-in-URL auto-approve).

## 6. Migration & rollout

**Coexistence:** email code stays wired end-to-end forever as the floor; nothing is removed. Legacy `/v1` mode is untouched (browser methods raise 501 → email path), preserving the `_uses_arcforge_gateway()` contract.

**Capability detection:** `GET /api/account/auth/desktop`; `ProClientError` in `{404, 405, 501}` → cache "unsupported", UI shows email flow (today's behavior, minus the "unavailable" apology copy). Identical in spirit to `_upload_meeting_audio_signed` and `_register_gateway_device` degradation. Result cached per process; "Refresh" re-probes.

**Phases:**
1. **Gateway:** discovery + `device-code` + `token` grant extensions + `/deck/link` + consent page + `authorize`. Ship behind a gateway feature flag; verify with curl + a scripted client before any desktop release. (Device grant is the smaller server surface — it can even ship one release ahead of `authorize`; the client ladder degrades correctly.)
2. **Client:** `browser_auth.py`, `ProClient` methods, UI-server routes, behind `DICTATE_PRO_BROWSER_SIGNIN=1` (default off). Beta channel first (Pro-gated beta updates already exist). Email-code UI remains the visible default.
3. **UI:** replace the signed-out block with §4; flag flips default-on; "Browser sign-in unavailable" copy deleted. Stable release.
4. **Cleanup:** remove the env flag; keep discovery probe permanently (self-hosted/older gateways).

**Rollback:** flag off client-side, or 404 the discovery endpoint gateway-side — either instantly reverts every client to email code with no data migration (session/token formats are unchanged throughout).

## 7. Open questions / risks (human decisions)

1. **Consent friction vs. silent SSO:** if the browser already has a `/deck` session, should Approve be required every time (recommended — the consent click is the whole security story for loopback), or skipped for repeat sign-ins from the same account? Recommend: always require the click.
2. **Consent page ownership:** the console bundle has OAuth handoff routes for other integrations — reuse that component styled for Dictate, or a new minimal page? Affects gateway estimate only.
3. **Session lifetime policy:** 30-day rotating refresh matches the client's current assumption; product may want "keep me signed in" (90 d) vs strict (7 d). Client reads whatever the server returns, so this is purely a server policy knob — but decide before GA since shortening later logs everyone out.
4. **Full device-key proof-of-possession (§5.7):** invest now or after multi-device sync usage grows? Recommendation: defer; fingerprint-binding gives revocation leverage cheaply.
5. **Publish `/.well-known/openid-configuration`?** Aliasing §2.1 would let standard OAuth tooling test the gateway, but also advertises the surface publicly. Not required by this design.
6. **`webbrowser.open` reliability matrix** (Linux under Wayland/Flatpak/snap, Windows default-browser edge cases): the "Open sign-in page" manual link is the mitigation, but decide whether to invest in `xdg-open`-first logic.
7. **Rate limits:** concrete numbers needed for `device-code` issuance (suggest 10/hr/IP), user-code entry (§2.4), and token polling (RFC `slow_down` handles the client side).
8. **Multiple concurrent desktops** signing in near-simultaneously on one account: no conflict in this design (independent codes/devices), but confirm the portal device list UX copes with several "Dictate on X" entries.

---

**Key file anchors for implementers:** gateway grant handling reuses the response shape consumed by `_session_from_arcforge_auth_response` (`src/dictate/pro/client.py:481`); token persistence is `save_session` (`client.py:81`); device registration reuse is `_register_gateway_device` (`client.py:436`); backend wiring pattern is `complete_pro_sign_in` (`src/dictate/ui_server.py:536`) with routes added beside `ui_server.py:1794`; device keys come from `generate_device_key_pair` (`src/dictate/sync.py:151`); the UI block to replace is `ui/src/App.jsx:589-603`.

---

*Authored by Fable 5 (design), 2026-07-06. Proposal for review — no code changes made.*
