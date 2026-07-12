# Forge handover — Dictate Arc Forge platform

**Date:** 2026-07-12 (Australia/Adelaide)  
**Repository:** `/home/samuel/repos/dictate`  
**Branch:** `forge/dictate-pro-platform`  
**Handover base:** `77b1c471281a9fe0f08a3c5d05c0eaf8782eab3c`

## Objective and execution authority

Continue the Forge build loop for [the active goal](goal.md). The user asked for
the plan to be built end to end. The current goal uses Wave 0 through Wave 4 and
requires Luna to build coherent waves, a quick conductor gate, and a fresh Sol
review only after each complete wave.

Do not push, merge, deploy, release, or mutate another repository without an
explicit human go. Local implementation commits on this branch are authorized.

## Completed work

The original dirty work was understood, tested, and folded into a clean
baseline before implementation continued. The branch now contains these
milestones, in order:

| Commit | Purpose |
| --- | --- |
| `a70977d` | Establish Dictate Pro platform baseline from the original dirty work |
| `c1d5240` | Fix accepted baseline review findings |
| `9e4dcf5` | Harden AppImage fallback and account wording |
| `48b4c7c` | Add the initial Wave/Phase 0 contract inventory |
| `dead1bd` | Correct `/api` versus `/v1`, backend evidence, privacy, usage, and state modeling |
| `28006cc` | Commit the user's shortened 204-line execution plan (199-line rewrite plus the later Wave 0 status block) |
| `96b974c` | Lock proposed Wave 0 authorities and implementable contract shapes |
| `77b1c47` | Harden URL, OAuth, sync-envelope, usage, privacy, diarization, and citation semantics |
| `d552dce` | Close Wave 0 P1s: key-envelope signature bundle schema and usage idempotency lifecycle |

Wave 0 is marked **PASSED — planning authority lock only**. This does not claim
that any shared backend or live deployment conforms. Unknown deployment facts
remain Wave 1–4 verification tasks and do not block independent implementation.

Primary artifacts:

- [Platform contract](contracts/dictate-platform-v1.json)
- [Platform inventory](platform/dictate-platform-inventory-v1.md)
- [Backend handoff](platform/arc-forge-backend-handoff-v1.md)
- [Contract tests](../tests/test_dictate_platform_contract.py)

## Wave 1 Slice 1 — durable desktop auth foundation

**Status:** done locally on `arc-forge-deck` branch `forge/wave1-durable-auth`
(commit `2a19ec4`; not pushed).

Implemented in the shared backend (read/write authorized for this Forge round):

1. Dictate desktop auth codes, device codes, and refresh tokens persist in
   hashed SQLite tables via `DurableAuthStore` — no longer only in process-memory
   dicts for `/api/account/auth/*` desktop paths.
2. Refresh tokens are stored hashed; rotation is durable; replay of a consumed
   refresh token fails closed and revokes the refresh family.
3. Discovery and device-code `verification_uri` emit canonical HTTPS endpoints
   from configured `DECK_PUBLIC_BASE_URL`, not raw `request.base_url` HTTP.
4. Token responses from account auth include `account_id` (and `device_id` when
   known) per `TokenResponse` in `docs/contracts/dictate-platform-v1.json`.
5. Executable restart/replay test: `tests/test_durable_auth.py`.

## Wave 1 Slice 2 — commerce single authority + usage ledger lifecycle

**Status:** done locally on `arc-forge-deck` branch `forge/wave1-durable-auth`
(commits `2ca2b8c` initial, `6fef9a6` Round 2, `28caac1` Round 3; not pushed).

Implemented in the shared backend:

1. **Single commerce authority** — `dictate_entitlement_for` and
   `_require_active_dictate_subscription` read `CommerceSubscription` +
   `Entitlement` only. Legacy `DictateSubscription` rows are one-way bridged on
   first read via `_bridge_legacy_dictate_subscription_to_commerce` (Stripe
   webhooks still ingest legacy rows; they are not a competing gate authority).
   Stale commerce rows re-project when legacy `updated_at` is newer.
2. **Usage ledger lifecycle** — new `DictateUsageLedger` module with
   reservation → settlement|rollback|rejection, gateway correlation fields
   (`request_id`, `idempotency_key`, `correlation_id`), and event_type-scoped
   retry dedup per `usage_events.idempotency_model` in
   `docs/contracts/dictate-platform-v1.json`. `DictateUsageEvent` model and DB
   migration extended; job create reserves, reconcile settles (auto-extending
   reservation when actual exceeds initial estimate), failure paths rollback with
   period compensation on ledger errors.
3. **Terminal exclusivity** — partial unique index
   `uq_dictate_usage_terminal_correlation` plus reservation row lock before
   terminal insert; `IntegrityError` maps to `UsageTerminalConflictError`.
4. **Executable tests** — `tests/test_dictate_usage_ledger.py` (reserve→settle
   idempotent retry, over-settlement without amendment, actual>reserve settle
   with amendment, terminal exclusivity serial + DB constraint, commerce refresh,
   duplicate-key rejection).
5. **Round 3** — `_release_job_usage` no-ops when any terminal ledger outcome
   exists (prevents quota leak after settlement); trialing subscriptions report
   `active: true` with `status: trialing`.

Remaining Wave 1 work (not in Slice 2): hosted jobs hardening (Wave 2 overlap),
sync/devices UX (Wave 3), portal browser `portal_refresh` cookie durability.

## Wave 1 Slice 3 — neutral login return + Dictate product destinations

**Status:** done locally on `arc-forge-deck` branch `forge/wave1-durable-auth` and
`dictate` branch `forge/dictate-pro-platform` (not pushed).

Implemented:

1. **Neutral account login entry** — unauthenticated Dictate consent (`/api/account/auth/authorize`)
   and device-link (`/account/link`, legacy `/deck/link`) redirect to `/account/login?next=…&continue=dictate`
   instead of hard-forcing `/deck/login`. `/login` also routes through `/account/login` when Svelte is enabled.
   Unsafe `next` values (absolute URLs, `//evil`, backslashes) are stripped before hand-off to the login SPA.
2. **Dictate product portal** — session-gated HTML destinations at `/dictate` with sub-pages for
   plan, usage, billing, devices, and sync-recovery. Device-code `verification_uri` now advertises
   `/account/link`.
3. **Dictate desktop client** — `ACCOUNT_PORTAL_URL` → `https://deck.arcforge.au/dictate`;
   `src/dictate/pro/product_destinations.py` documents durable destination URLs.
4. **Executable tests** — `tests/test_dictate_account_return.py` (next/continue preservation,
   evil-host rejection); updated `tests/test_dictate_desktop_auth.py`.

**Wave 1 gate:** Slices 1–3 complete locally. Residual: `portal_refresh` cookies remain
in-memory (not durable); full Svelte `/dictate` section can replace HTML shell later.

## Wave 2 Round 1 — governed hosted transcription

**Status:** done locally on `arc-forge-deck` branch `forge/wave1-durable-auth`
(Wave 1–2 backend branch) and `dictate` branch `forge/dictate-pro-platform` (not pushed).

Implemented in this round:

1. **Durable hosted job lifecycle** — worker-owned create/upload/status/result/ack/cancel
   with idempotent completion (`worker_should_skip`, `persist_hosted_result_artifact`) and
   restart-safe artifact retrieval after lost responses.
2. **Capability gate** — job create accepts `dictate.transcribe` / `dictate.transcribe_diarized`;
   clients never receive provider credentials.
3. **Usage ledger wiring** — hosted path settles via existing `DictateUsageLedger`
   (reserve on create, settle on success, rollback on cancel/failure).
4. **Encrypted results** — `DictateResultArtifact` model with server-managed AES-256-GCM
   (platform secret + account/device/job AAD; not device-key wrapped yet),
   ack/delete-after-ack, configurable TTL.
5. **Audio cleanup** — local spool and object-store uploads deleted on success,
   failure, cancel, and TTL expiry.
6. **Executable tests** — `tests/test_dictate_hosted_jobs.py` (happy path, restart,
   idempotent ack, quota rejection, cross-account denial, audio cleanup).
7. **Dictate client** — `get_result`, `ack_result`, `cancel_job`, `capability` on create.

**Deferred within Wave 2:** device public-key wrapping for result decryption;
separate worker process vs in-request durable commits.

## Wave 2 Round 2 — conductor security fixes

**Status:** done locally (not pushed).

1. **[P0]** Hosted result encryption fails closed when `PORTAL_JWT_SECRET` is missing;
   no default fixture secret.
2. **[P1]** Object-store audio deleted via `artifact_store.delete_object` on
   success/failure/cancel/TTL (local spool unchanged).
3. **[P1]** Honest naming: `server_managed_encrypted_artifact` replaces
   overclaimed owner-bound labels in backend, contract, and handover. AES+AAD
   account isolation retained; device-key wrapping deferred.

**Wave 2 Round 1 commits:** `6896fc4` (arc-forge-deck), `ea673cc` (dictate).
**Wave 2 Round 2 commits:** `d069430` (arc-forge-deck), `810100c` (dictate).

## Wave 2 Round 3 — contract wording cleanup

**Status:** done locally (not pushed).

1. **[P2]** `hosted.result.idempotency.replay` and residual hosted-result contract
   text use server-managed encrypted artifact wording (no owner-bound claims).

**Wave 2 Round 3:** contract `hosted.result.idempotency.replay` server-managed wording (dictate).

## Wave 3 Round 1 — devices, encrypted sync, desktop convergence

**Status:** done locally (not pushed).

Implemented in this round:

1. **Unified device revocation** — `revoke_dictate_device_unified` revokes the
   `DictateDevice`, all refresh families for that `device_id`, and marks the sync
   cursor `revoked`. Refresh rotation fails closed after revoke; sync push and
   registered-device hosted work return 403.
2. **Device registry API** — `GET/POST /api/dictate/devices`,
   `POST /api/dictate/devices/register`, approve/revoke routes, and
   `POST /api/dictate/devices/current/approve-with-recovery` (fail-closed `501`
   until crypto verification ships).
3. **Encrypted sync path** — push/pull/cursor/key-envelope routes accept contract
   `SyncEnvelope` fields (`envelopes`) plus legacy `records`; server stores
   ciphertext only; cross-account envelope push denied.
4. **Hosted gate** — `require_hosted_dictate_device` blocks registered revoked or
   pending devices without breaking legacy jobs that pass an unregistered
   `device_id`.
5. **Dictate desktop convergence** — `platform_state.py` classifies
   auth expiry, gateway outage, entitlement inactive, quota, provider failure,
   sync paused, and device revoked; `ProClient.get_state()` keeps session on
   transient outages; `ui_server._sync_state()` exposes `state` + `convergence`.
6. **Executable tests** — `tests/test_dictate_devices_sync.py` (deck);
   `tests/test_platform_state.py` plus `ProClient` outage/revoke tests (dictate).

**Deferred within Wave 3:** `sync.export` / `sync.delete`; full AAD hash
verification; device public-key wrapping for hosted results; background sync
loop; macOS Keychain; bind `device_id` on device-code token grant; portal
`PortalDevice` vs `DictateDevice` unification.

**Wave 3 Round 1 commits:** `cbbda15` (arc-forge-deck), `d23adc3` (dictate).

## Wave 3 Round 2 — conductor security fixes

**Status:** done locally (not pushed).

1. **[P0]** Recovery approve endpoint fail-closed (`501`) until cryptographic
   recovery envelope verification ships; pending devices stay pending.
2. **[P1]** Access JWTs mint `device_id` on refresh (and optional token-exchange
   `device_id`); sync/device-mutating routes require matching bearer claim;
   registered-device hosted jobs require bound access tokens.
3. **[P2]** Key-envelope list requires `device_id` + trusted-device gate.
4. **[P2]** Sync AAD constrained to contract allowlist (`SyncAuthenticatedMetadata`
   keys only); unknown fields rejected.

**Deferred:** full recovery-key crypto verification; device-code grant `device_id`
binding at mint; hosted spoof hardening for unregistered legacy `device_id` strings.

**Wave 3 Round 2 commits:** `779daf9` (arc-forge-deck), `b6b347d` (dictate).

## Wave 4 Round 1 — integrate, migrate, release prep (local proof)

**Status:** done locally (not pushed, not deployed).

1. **Residual auth quarantine** — `residual_interim_auth.py` documents
   non-durable stores (`_login_codes`, companion `_auth_codes`, `portal_refresh`);
   Dictate desktop OAuth/device/refresh paths remain on `DurableAuthStore`.
2. **Commerce honesty** — `_ensure_canonical_dictate_commerce` documented as single
   authority; legacy `DictateSubscription` is one-way bridge only (no dual-read).
3. **Docs alignment** — `goal.md`, backend handoff, inventory overlay, privacy
   policy updated for server-managed hosted results and not-deployed honesty.
4. **Release readiness** — [forge-wave4-release-readiness-2026-07-12.md](forge-wave4-release-readiness-2026-07-12.md)
   records local proof, UNKNOWN deploy facts, rollback notes, residual risks.
5. **Broad gates** — deck 124, dictate 221, ui vitest 98 (see below).

**Out of scope:** push, merge, Helm, live canary, production credentials.

**Wave 4 Round 1 commits:** `67914b9` (arc-forge-deck), `57d02c6` (dictate).

**Wave 4 Round 2 commits:** `965fe40` (arc-forge-deck), `ab65a65` (dictate); tip SHA record `584b3f6` (dictate).

**Branch tips (local, not pushed):**
- arc-forge-deck `forge/wave1-durable-auth` @ **`965fe40`**
- dictate `forge/dictate-pro-platform` @ **`1423030`**

## Wave 4 Round 2 — conductor doc fixes

**Status:** done locally (not pushed).

1. **[P2]** Residual risks expanded — MFA, magic-link, password-reset, browser
   `_refresh_tokens` added to readiness doc matching `residual_interim_auth.py`.
2. **[P2]** `residual_interim_auth.py` complete — `_magic_tokens`, `_refresh_tokens`
   inventory; RESIDUAL_INTERIM labels on matching `dashboard.py` sites.
3. **[P2]** Tip SHAs recorded separately from Round 1 commit list in readiness
   and handover.
4. **[P3]** Inventory stale rows annotated superseded by forge overlay /
   DurableAuthStore / server-managed artifacts.

## Wave 4 Round 3 — tip SHA honesty

**Status:** done locally (not pushed).

1. **[P2]** Aligned dictate branch tip fields in readiness and handover so both
   document the same local HEAD after this commit (no internal contradiction).
2. **[P2]** Incorporated the uncommitted handover boundary fix and retired stale
   `4cc83f0` / `584b3f6` split across readiness vs external boundary block.

**Wave 4 Round 3 commit:** `1c5ebf7` (dictate); deck tip unchanged `965fe40`.

## Docs hygiene — continuous E2E tracking

**Status:** done locally (not pushed).

1. **[P2]** Refreshed [goal.md](goal.md) as living E2E authority — progress
   scoreboard, Wave 1–2 status lines, Wave 4 Rounds 1–3 summary, explicit
   push/canary/deploy gate.
2. **[P2]** Redirected [GOALS.md](GOALS.md) to `goal.md` (platform) vs
   `TRANSCRIPTION_PLAN.md` (local transcription).
3. **[P3]** Added superseding banners on `desktop-browser-signin-architecture.md`
   and `DICTATE_PRO_CLOUD_SYNC_PLAN.md` where claims could lag forge truth.

**E2E scoreboard of record:** [goal.md](goal.md). This handover is session
continuity; release evidence is
[forge-wave4-release-readiness-2026-07-12.md](forge-wave4-release-readiness-2026-07-12.md).

## Waves 0–4 local status

| Wave | Status |
| --- | --- |
| Wave 0 | **PASSED** — planning authority lock |
| Wave 1 | **COMPLETE LOCAL** — durable auth, commerce, usage, neutral login |
| Wave 2 | **COMPLETE LOCAL** — governed hosted transcription |
| Wave 3 | **COMPLETE LOCAL** — devices, sync, desktop convergence |
| Wave 4 R1 | **COMPLETE LOCAL PROOF** — docs/integration gates; pending human deploy go |
| Wave 4 R2 | **COMPLETE LOCAL** — residual auth inventory + doc SHA fixes |
| Wave 4 R3 | **COMPLETE LOCAL** — tip SHA honesty across readiness + handover |
| Docs hygiene | **COMPLETE LOCAL** — `goal.md` scoreboard + stale-doc redirects |

Nothing has been pushed, merged, deployed, or released.

## Recommended next actions (human gate)

1. Review [goal.md](goal.md) scoreboard and
   [forge-wave4-release-readiness-2026-07-12.md](forge-wave4-release-readiness-2026-07-12.md).
2. Authorize push of both forge branches when ready.
3. Record deployed SHA; run discovery HTTPS + migration dry-run + internal canary.
4. Wave 4 Rounds 2–4 may continue local hardening before deploy go.

## Last independently verified gates

Wave 4 Round 1 broad gates (both repos, not pushed):

```text
arc-forge-deck:
  uv run python -m pytest tests/test_dictate_devices_sync.py tests/test_dictate_hosted_jobs.py tests/test_dictate_usage_ledger.py tests/test_durable_auth.py tests/test_dictate.py tests/test_dictate_desktop_auth.py tests/test_dictate_account_return.py tests/test_commerce.py -q   PASS (124)
  git diff --check                                                                                                  PASS

dictate:
  .venv/bin/pytest -q tests/test_dictate_platform_contract.py tests/test_pro_client.py tests/test_platform_state.py tests/test_pro_auth.py tests/test_pro_service.py tests/test_ui_server.py tests/test_sync.py tests/test_sync_engine.py tests/test_browser_auth.py   PASS (221)
  cd ui && npm test                                                                                                 PASS (98)
  git diff --check                                                                                                  PASS
```

Prior Wave 3 Round 2 gates at `779daf9` / `b102c33`.

Useful focused commands:

```bash
# arc-forge-deck
uv run python -m pytest tests/ -k "entitle or commerce or usage or dictate_subscription or durable_auth" -q
uv run python -m pytest tests/test_dictate_desktop_auth.py tests/test_durable_auth.py -q
git diff --check

# dictate
python3 -m compileall -q src tests scripts
.venv/bin/pytest -q tests/test_dictate_platform_contract.py tests/test_pro_client.py tests/test_platform_state.py
git diff --check
```

## External repository boundary

The shared backend implementation for Wave 1 lives on:

```text
/home/samuel/repos/arc-forge-deck
branch: forge/wave1-durable-auth
parent: forge/handover-sharpen @ ae663a0
Wave 4 Round 1: 67914b9
Wave 4 Round 2: 965fe40
branch tip (local): 965fe40

/home/samuel/repos/dictate
branch: forge/dictate-pro-platform
Wave 4 Round 1: 57d02c6 (+ handover fix 6c1faa8)
branch tip (local): 1423030
```

Do not push, merge, or deploy without explicit human go.

Nothing on this Dictate branch has been pushed, merged, deployed, or released.
