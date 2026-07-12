# Goal — Finish Dictate on the Arc Forge Account and Usage Platform

**Status:** Current cross-system goal and planning authority.

This file governs the shared Arc Forge identity, Dictate product, Dictate Pro
paid offering, hosted usage, sync, Deck boundary, migration, and release proof.
The narrower documents below remain useful, but they are subordinate inputs and
must not establish a competing cross-system architecture.

### Planning authority map

| Document | Status and authority |
| --- | --- |
| `docs/goal.md` | Current authority for cross-system product and architecture decisions. |
| `docs/TRANSCRIPTION_PLAN.md` | Active scoped authority only for local transcription and release evidence; subordinate to this goal for account, cloud, commerce, and Deck decisions. |
| `docs/DICTATE_PRO_CLOUD_SYNC_PLAN.md` | Reference and migration input for cloud sync/account detail; subordinate to this goal. |
| `docs/deck-sections-and-dictate-space-spec.md` | Proposed Deck-space reference and migration input; subordinate to this goal for product/account semantics. |

When these documents disagree, this goal controls the cross-system decision and
the narrower document records the resulting migration or implementation detail.

## Phase 0 execution status

**Status:** PENDING — not passed. Dictate-side contract, inventory, and backend
handoff evidence are recorded for owner confirmation; no shared backend or live
implementation is claimed to match them.

The Phase 0 contract separates current non-loopback `/api` client compatibility
from local or explicitly legacy `/v1` reference behavior, and records external
source implementation separately from **UNKNOWN** deployment verification.

- [Machine-readable contract v1](contracts/dictate-platform-v1.json)
- [Dictate platform inventory v1](platform/dictate-platform-inventory-v1.md)
- [Arc Forge backend handoff v1](platform/arc-forge-backend-handoff-v1.md)

## Outcome

Dictate reaches a stable, cohesive product baseline. Local Dictate remains
complete without an account. Dictate uses the shared Arc Forge account,
commerce, entitlement, and hosted-model platform for its Dictate Pro offering
without exposing provider keys or borrowing Deck-specific identity and
language.

This goal is complete when:

- A person has one Arc Forge login. The login surface says **Arc Forge**, not
  Deck, Dictate, Console, or the name of whichever product initiated sign-in.
- The same Arc Forge account can enter Deck, Dictate, and future products.
  Each product has its own space and entitlements; none impersonates the account
  platform itself.
- Dictate hosted transcription, when enabled by the Dictate Pro offering, runs
  through the approved shared Arc Forge model-usage tooling, with server-side
  credentials, policy checks, durable usage accounting, budgets, observability,
  and privacy-safe operations.
- The desktop's browser sign-in, email fallback, refresh, device registration,
  revocation, encrypted sync, hosted jobs, and account management survive normal
  deploys and service restarts.
- Interim Dictate hosted paths are either promoted to the production contract
  or removed. The in-repo `/v1` Pro server remains only a labelled
  test/reference harness and cannot be mistaken for production architecture.
- Current code, live deployment, tests, user-facing copy, and current
  documentation describe the same system.

The desired product model is the same one used by Google: a neutral company
login establishes identity, then the person enters the product they intended to
use. An Arc Forge account may use Dictate with the Dictate Pro offering, use
Deck, use both, or use neither. Login is not
an advertisement for another product.

## Scope rule

Finish and consolidate what already exists before adding new product surface.

In scope:

- Dictate desktop account and hosted-usage integration.
- Dictate identity, Dictate Pro entitlement/commerce, devices, encrypted sync,
  hosted jobs, usage accounting, and account UX.
- Shared Arc Forge login branding and return-to-product behavior needed by
  Dictate.
- The shared Arc Forge hosted-model contract used by Dictate and Deck.
- Durable authentication and grant state required for desktop clients.
- Migration from legacy `console.arcforge.au` and `/deck/*` assumptions to the
  approved canonical Arc Forge account/product routes.
- Removal or archival of superseded Dictate Pro code, flags, routes, and current
  documentation after production cutover is proven.

Out of scope:

- Redesigning Deck while its own stabilization goal is active.
- Moving Deck's unrelated agents, provisioning, runtime delivery, or deployment
  work into this repository.
- A new identity provider, a second account database, or a second commerce
  authority.
- A speculative universal AI router. The shared gateway must support proven
  product lanes and grow by explicit capability.
- Team accounts, shared Dictate workspaces, raw-audio cloud backup, or new plan
  tiers before the single-account foundation is stable.
- Making cloud sign-in or sync mandatory for local Dictate.

## Coordination boundary with Deck

Deck is being stabilized in parallel by an active owner. Dictate must not create
a second source of truth or land broad opportunistic changes in that repository.

Rules:

1. Dictate owns its desktop client, local UI, local secret handling, encrypted
   sync client, hosted-job client, packaging, compatibility, and product tests.
2. The Arc Forge account/gateway backend owns shared identity, login sessions,
   OAuth grants, device authorization, commerce projection, entitlements,
   provider credentials, hosted usage policy, and production job APIs.
3. Deck owns its product UI and its use of the shared platform. Dictate must not
   couple to Deck navigation, Deck entitlements, agent tenancy, or agent usage.
4. Cross-repository work starts with a versioned contract and a named handoff.
   It lands as narrow backend or account-shell changes that the Deck owner can
   review against Deck's current goal.
5. Do not merge a cross-repo change while it conflicts with an unresolved Deck
   architecture decision. Record the dependency and continue with Dictate-side
   contract tests, mocks, migrations, and fallback work that does not require the
   contested change.
6. Do not revive `forge-llm-gateway` as another production authority merely
   because it exists. First decide which deployed service owns the shared model
   contract. Prefer extending the currently deployed Arc Forge gateway behind a
   stable interface over operating two overlapping gateways.

## Non-negotiable product and architecture rules

### One neutral Arc Forge identity

- `PortalAccount.account_id` is the account and data-ownership boundary.
- Stripe customer IDs are billing references, not primary user identity.
- Access tokens use the Arc Forge account ID as their subject.
- Browser sessions and desktop sessions are different clients of the same
  account platform.
- The login page and login emails use Arc Forge identity. Product-specific copy
  may say which app requested access, but the page itself does not brand the
  account as Deck.
- Successful login returns to the initiating product and validated continuation
  path. Dictate authorization returns to Dictate consent and then the desktop;
  it never drops the user into an unrelated agent screen.
- Authorization Code with PKCE is the primary desktop flow. Device Authorization
  Grant is the remote/headless fallback. Email code remains the dependable final
  fallback.
- Public native clients have no client secret.

### Separate products and paid offerings on one account

- Deck and Dictate share account, commerce, and gateway primitives.
- Dictate is the product and product space. Dictate Pro is its paid offering,
  plan, entitlement, and hosted/sync capabilities; it is not a second product
  or account identity.
- `deck_agent` and `dictate_pro` remain separate entitlements.
- Deck agent/model usage and Dictate audio-second usage remain separate product
  ledgers, even when they use the same underlying gateway machinery.
- A free Arc Forge account can open the account hub and see available products,
  downloads, and purchase paths without being provisioned into Deck or the
  Dictate Pro offering automatically.
- Dictate's account destination is its Arc Forge product space, not the agent
  dashboard. The target route is canonical, deep-linkable, and compatible with
  old links during a bounded migration.

### Shared hosted-model gateway, product-owned semantics

- Provider credentials exist only in the server runtime secret boundary. They
  never ship in Dictate, Deck, browser payloads, logs, sync records, or support
  exports.
- A shared gateway layer owns provider authentication, allowlisted provider/model
  routes, timeout/retry policy, request correlation, provider error
  normalization, cost/usage telemetry, and secret resolution.
- Each product owns the meaning of its usage. Dictate reserves and settles audio
  seconds. Deck owns its token/request/tool budgets. Shared tooling does not mean
  a shared undifferentiated quota.
- LiteLLM may implement supported text/model lanes. Audio transcription may use
  a dedicated adapter until LiteLLM supports the required API and response
  semantics. Both still enter through the same policy, identity, telemetry,
  budget, and audit contract.
- Every hosted request carries an authenticated account ID, product (`dictate`
  or `deck`), feature, provider alias, model alias, credential mode, request ID,
  and idempotency key where billing can change.
- Provider names and upstream keys are not the desktop contract. Dictate asks for
  a product capability such as `dictate.transcribe` or
  `dictate.transcribe_diarized`; the server selects an approved route.
- Gateway logs and metrics contain no audio, prompt, transcript, hotword,
  dictated text, access token, refresh token, provider key, or signed upload URL.

### Local-first privacy

- Dictate remains usable without an Arc Forge account.
- Sign-in does not enable sync. Sync requires explicit consent.
- Synced dictated content is encrypted on the client before upload.
- Raw audio is not part of normal sync.
- Hosted transcription is a separate, explicit privacy boundary: audio leaves
  the device for that job, is retained only for the bounded processing window,
  and is deleted according to a tested lifecycle.
- The server may meter hosted work and retain non-content job metadata, but it
  must not retain readable transcript content after delivery.

### Hosted result handoff contract

- Worker completion is durable independently of the request that submitted the
  job or the client poll that observes completion.
- A completed result is an owner-bound encrypted artifact. Retrieval and
  acknowledgement require the authenticated owning account/device and are
  idempotent, so a lost response or repeated request cannot expose another
  account's result or create a second delivery.
- Result artifacts, temporary plaintext, and any acknowledgement window have
  explicit bounded expiry and deletion rules. Completion is not a license to
  retain readable transcript content indefinitely.
- The proof must cover worker completion versus client polling, restart and lost
  response, duplicate retrieval and acknowledgement, account isolation,
  expiry/deletion, and the full plaintext lifetime.

### Durable, revocable sessions

- Refresh-token families, authorization codes, device codes, consent replay
  guards, and rate-limit state that must survive a deploy do not live only in
  process memory.
- Refresh tokens are stored hashed, rotated on use, have a short retry grace
  window, detect reuse, and support family/account/device revocation.
- Device revocation invalidates its refresh family and prevents sync or hosted
  jobs from that device.
- A downstream commerce, entitlement, usage, or provider outage must not erase a
  valid local desktop session. Only definitive authentication failure clears
  credentials.

## Target system

```text
Arc Forge login
  └─ PortalAccount.account_id
       ├─ browser session → Arc Forge account hub
       │                    ├─ Deck product space
       │                    └─ Dictate product space
       └─ desktop OAuth session → Dictate
                                ├─ dictate_pro entitlement
                                ├─ trusted device + encrypted sync
                                └─ Dictate hosted job
                                     └─ shared model gateway policy
                                          └─ approved STT provider adapter
```

The account platform authenticates. Commerce grants product entitlements. The
shared model gateway authorizes and observes provider use. Dictate owns the
recording/transcription workflow and encrypted local/sync data. These are
separate responsibilities with explicit contracts.

## Attack order

Work in this order. Do not start a later phase while an earlier phase has an
unresolved ownership or data-authority decision.

### Phase 0 — Freeze contracts and inventory reality

1. Name the active owner for Dictate, the Arc Forge account/gateway backend, and
   Deck stabilization.
2. Record the deployed services, repositories, revisions, public domains,
   reverse proxies, databases, object stores, workers, provider adapters, and
   release lanes involved in Dictate Pro.
3. Inventory every Dictate/Arc Forge account route, token/grant store, portal
   route, entitlement row, Stripe projection, usage table, audio store, provider
   secret, feature flag, and legacy `/v1` path.
4. Classify each as production authority, compatibility path, test harness,
   migration input, or dead interim work.
5. Write versioned contracts for:
   - account discovery and login;
   - token and refresh behavior;
   - product entitlement and commerce status;
   - device registration/revocation;
   - sync;
   - hosted job create/upload/status/result;
   - shared gateway invocation and usage events.
6. Agree with the Deck owner on the smallest shared-backend changes and the
   canonical account/product routes. Record them as a handoff, not an implicit
   dependency on uncommitted Deck work.

Gate: every live path has one authority and disposition; Dictate and Deck owners
agree on the shared contracts and repo boundaries.

### Phase 1 — Make the Arc Forge account platform durable

1. Move refresh tokens, refresh families, desktop authorization codes, device
   codes, consent replay records, and required rate-limit state from process
   dictionaries to Postgres or an approved durable TTL store.
2. Store only hashes for bearer-style refresh, authorization, and device codes.
3. Implement atomic single-use consumption, refresh rotation, retry grace,
   reuse detection, expiry cleanup, device binding, and account/device/family
   revocation.
4. Preserve access JWT validation through normal deploys and prove refresh
   across gateway restart, rolling deployment, and request retry.
5. Keep portal browser sessions and desktop access tokens distinct by token type
   and audience. Consent endpoints accept browser session tokens only.
6. Make all externally generated URLs use a configured canonical HTTPS origin or
   correctly trusted proxy headers. Reject a production startup whose discovery
   document advertises insecure public URLs.
7. Add production-shaped tests for multiple workers, restart between issue and
   exchange, restart between refreshes, replay, expiry, revocation, and proxy
   scheme handling.

Gate: no valid 30-day desktop session depends on one Python process; live
discovery and device verification advertise HTTPS and survive deployment.

### Phase 2 — Establish generic Arc Forge login and product return

1. Replace Deck-specific login branding with Arc Forge account branding in the
   shared login shell, login emails, MFA, recovery, and consent chrome.
2. Keep product context narrowly scoped: “Dictate is requesting access” belongs
   on the consent step, not in the identity brand.
3. Define and validate a same-origin continuation contract used by password,
   email code, magic link, Google login, MFA, and recovery. Every method returns
   to the original consent/product destination.
4. Complete PKCE loopback consent and device-link approval with CSRF, exact
   redirect validation, rate limits, single-use grants, and privacy-safe audit
   events.
5. Turn Dictate browser sign-in on by capability discovery rather than a hidden
   release environment flag. Retain email code automatically when discovery is
   unavailable.
6. Build the neutral Arc Forge account hub behavior: a user can see available
   product spaces and purchase paths without being redirected into Agents.
7. Provide a Dictate product destination containing plan, usage, billing,
   devices, sync/recovery status, downloads, privacy controls, export, and cloud
   deletion. Coordinate this surface with the Deck owner; do not redesign Deck's
   unrelated sections.
8. Migrate desktop and gateway links from legacy Console/`/deck` URLs to the
   canonical Arc Forge routes with tested redirects for old releases.

Gate: a new user and an existing Deck user can sign into Dictate through every
supported method, approve the desktop, return to Dictate, and manage Dictate
without seeing misleading Deck branding or an agent-first landing page.

### Phase 3 — Define and prove the shared model-usage contract

1. Choose the deployed owner of shared model routing. Document why the current
   Arc Forge gateway, LiteLLM, or another existing component is authoritative;
   do not leave two production gateways active for the same lane.
2. Define a provider-neutral request envelope and normalized result/error model.
3. Define shared middleware for:
   - account/product/feature authorization;
   - entitlement and budget checks;
   - request IDs and tracing;
   - idempotency;
   - timeout, retry, and circuit-breaker policy;
   - provider/model allowlists;
   - usage reservation, settlement, and rollback;
   - privacy-safe metrics and audit events.
4. Route supported Deck text/model lanes through this tooling without changing
   Deck product semantics.
5. Route Dictate hosted transcription through the same tooling. If STT remains a
   direct xAI adapter, place it behind the shared middleware and capability
   registry rather than calling provider code as an exceptional side path.
6. Resolve provider credentials from a runtime secret file or platform-native
   secret injection. Prohibit plaintext keys in repository config, database
   rows, client payloads, or logs.
7. Prove provider failure, timeout, throttling, malformed response, usage
   rollback, duplicate request, and failover behavior with recorded sanitized
   fixtures.

Gate: Dictate and Deck use one observable, governed model-access foundation;
Dictate clients never receive or require an upstream provider key.

### Phase 4 — Make Dictate usage and commerce authoritative

1. Keep one Stripe webhook authority and one shared commerce subscription model.
2. Make Dictate's Stripe price map explicitly to product `dictate`, paid plan
   `dictate_pro_monthly`, and entitlement `dictate_pro`. Never feed it through
   Deck's agent price map.
3. Backfill and reconcile legacy Dictate subscription rows into shared commerce,
   then choose one read authority and remove dual-read ambiguity.
4. Define subscription states once, including the exact policy for `past_due`,
   grace, cancellation, expiry, refund, and Store-issued access. Use the same
   interpretation in commerce, entitlement, desktop state, sync, and hosted
   jobs.
5. Maintain a Dictate usage ledger in seconds with immutable events and a
   materialized period balance. Reserve before provider work, settle to measured
   duration, and roll back exactly once on failure.
6. Use idempotency keys and database constraints so retries cannot double-charge
   or create duplicate jobs.
7. Separate Dictate usage from Deck token usage while returning both through a
   consistent account-platform schema.
8. Add reconciliation jobs and operator reports for Stripe → commerce →
   entitlement and hosted job → usage event → period balance.

Gate: subscription and usage answers are identical across webhook processing,
account portal, desktop state, sync authorization, hosted-job authorization,
and operator reconciliation.

### Phase 5 — Finish the hosted transcription job lifecycle

1. Settle one canonical state machine: created, awaiting upload, uploaded,
   queued, processing, completed, failed, cancelled, expired, quota rejected.
2. Align desktop parsing and polling with the exact production response shape.
   Remove legacy/reference status assumptions from production code paths.
3. Prefer bounded signed object uploads. Constrain scheme, host, method, content
   type, byte size, checksum, ownership, expiry, and single completion.
4. Run provider work outside the request process through a durable worker/queue.
   Make retries idempotent and cap attempts.
5. Delete raw audio after success, terminal failure, cancellation, or TTL. Prove
   cleanup for local spool and object storage.
6. Return an owner-bound encrypted result artifact only to the authenticated
   owning client. Persist only the minimum job/segment metadata needed
   operationally; encrypt any transcript content that enters sync. Retrieval
   and acknowledgement are idempotent, and the artifact expires and is deleted
   on the tested privacy schedule.
7. Support capability-level routing for ordinary cloud dictation and diarized
   meetings without exposing provider brands as the account contract.
8. Add end-to-end tests from desktop audio to provider fixture to transcript,
   including quota, provider failure, restart, duplicate completion, deletion,
   and account isolation.
9. Prove worker completion versus client polling, lost responses, duplicate
   retrieval and acknowledgement, result expiry/deletion, and plaintext
   lifetime across worker and gateway restarts.

Gate: a hosted job is private, metered exactly once, restart-safe, observable,
and recoverable without manual database repair.

### Phase 6 — Finish devices and encrypted sync

1. Use the Arc Forge desktop session and canonical `account_id` for device
   registration.
2. Bind refresh families and sync device records so revocation has one clear
   effect across auth, sync, and hosted jobs.
3. Complete first-device, additional-device approval, recovery-key, revoke,
   export, and cloud-delete flows.
4. Verify the account data key and private device keys remain only in the OS
   secret store; the server receives public keys and encrypted envelopes only.
5. Enforce explicit sync opt-in and scope. Never upload local history merely
   because login succeeded.
6. Add multi-device conflict, revoked-device, lost-key, recovery, reinstall,
   offline outbox, cursor, and account-isolation tests.
7. Make partial gateway failures visible without silently disabling sync,
   deleting local data, or signing the user out.

Gate: two clean installations can join one account, approve securely, exchange
encrypted records, recover, revoke, export, and delete cloud data while local
Dictate remains intact.

### Phase 7 — Converge the desktop product

1. Present three distinct states: local Dictate, signed-in Arc Forge account,
   and explicitly enabled Dictate Pro sync/hosted capability in the Dictate
   product.
2. Remove “Pro” where the user is choosing execution location; use Local and
   Cloud. Use Dictate Pro only for the product entitlement/account offering.
3. Make account state resilient: distinguish signed out, session expired,
   gateway unavailable, entitlement inactive, quota exhausted, provider down,
   sync paused, and device revoked.
4. Clear credentials only on definitive auth failure. Cache the last verified
   account/entitlement state with an age indicator for bounded offline display.
5. Make local fallback explicit and safe when Cloud fails. Never silently send
   audio through a different hosted provider or personal key.
6. Remove the browser-login feature flag after stable rollout; retain capability
   discovery and email fallback permanently.
7. Update account, privacy, Store, onboarding, and support copy to explain Arc
   Forge identity, Dictate entitlement, encrypted sync, and hosted audio as
   separate concepts.

Gate: ordinary users can predict whether audio or text leaves the device, which
account they are using, what they are paying for, and how to recover from every
common failure without CLI intervention.

### Phase 8 — Prove, migrate, release, and remove interim architecture

1. Build one production-shaped integration environment using the same proxy,
   database, object-store mode, worker model, and secret-delivery contract as
   production.
2. Run contract tests from Dictate against the deployed gateway and from the
   gateway against provider fixtures. Keep tests independent of Deck UI layout.
3. Canary with internal accounts, then a small opt-in Dictate cohort. Observe
   login completion, refresh survival, job success, provider latency/error,
   usage reconciliation, audio cleanup, sync errors, and forced reauthentication.
4. Exercise rollback: gateway feature disable, provider route disable, desktop
   fallback to local, and compatibility redirects for existing clients.
5. Migrate legacy account subjects, subscriptions, refresh sessions, devices,
   usage rows, and portal links with explicit counts and reconciliation.
6. Remove or archive:
   - process-memory production auth stores;
   - legacy Console and redundant `/deck` client URLs after the compatibility
     window;
   - dual commerce/entitlement reads;
   - direct exceptional provider paths outside shared policy;
   - obsolete browser-signin flags;
   - production claims in the reference `/v1` server;
   - superseded current-plan documents.
7. Make this file, privacy policy, terms, deployment security, support runbooks,
   and live behavior agree.

Gate: stable release evidence passes; migration and rollback are proven; no live
caller depends on an interim path; current documentation has one architecture.

## Required proof matrix

The work is not complete without automated and operational evidence for:

| Area | Required proof |
| --- | --- |
| Identity | New/free/existing Deck/existing Dictate accounts resolve to one `account_id` without accidental merges. |
| Login | Password, Google, email code, PKCE, device code, MFA, cancellation, replay, timeout, and safe return path. |
| Durability | Issue before restart and exchange/refresh after restart; rolling deployment; concurrent refresh retry. |
| Revocation | Device, refresh family, account, and entitlement revocation block the correct surfaces only. |
| Commerce | Stripe lifecycle and Store access reconcile to the same Dictate entitlement policy. |
| Gateway | No client key; allowlists; budgets; timeout/retry; provider failure; redacted traces; account isolation. |
| Usage | Reservation, settlement, rollback, duplicate retry, period rollover, quota edge, and reconciliation. |
| Hosted jobs | Signed upload, ownership, restart, worker retry, transcript delivery, audio TTL deletion, cancellation. |
| Sync | Explicit consent, encryption, two-device approval, conflicts, offline outbox, recovery, revoke, export, delete. |
| Desktop | Local-only operation, Cloud success/failure/fallback, partial account outage, stale state, sign-out preservation. |
| Migration | Legacy URLs, account subjects, subscriptions, devices, sessions, and old desktop releases. |

## Stability and release gates

Before stable promotion:

1. No P0/P1 auth, cross-account, billing, provider-key, plaintext-content, or
   data-loss finding is open.
2. Refresh and pending grants survive a real gateway deployment.
3. Live discovery exposes only canonical HTTPS endpoints.
4. A Dictate account login never lands on an agent-first Deck screen.
5. Hosted requests are attributable by account/product/request ID without
   logging content or secrets.
6. Usage reconciliation shows no unexplained balance drift for the canary
   period.
7. Audio cleanup meets its TTL in both normal and failed jobs.
8. The desktop works locally throughout a full Arc Forge outage.
9. Existing released clients retain a bounded, tested compatibility path.
10. Deck's owner confirms shared backend changes do not regress Deck's active
    stabilization goal.

## Final definition of done

This goal is not achieved merely because the UI can sign in or one hosted
transcription succeeds. It is achieved when Arc Forge identity is neutral,
Dictate is a first-class product on that identity, with Dictate Pro as its paid
offering; Dictate and Deck share a governed model-usage foundation without
sharing accidental product semantics,
and every auth, billing, usage, sync, privacy, deployment, and recovery path is
durable and operationally boring.

At that point:

- Dictate contains no production provider secret.
- Deck is not a prerequisite or accidental landing page for Dictate.
- Dictate does not operate a parallel account universe; Dictate Pro is its
  product entitlement and capability set.
- Provider access is policy-controlled and observable.
- Deployments do not log users out.
- Usage is explainable and reconcilable.
- Local Dictate remains private and useful when every Arc Forge service is
  unavailable.
- The remaining code is the intended architecture, not scaffolding waiting for
  another pass.
