# Goal — Ship Dictate on the Arc Forge Platform

**Status:** Active execution authority.

**E2E objective not complete until human push/canary/deploy proof.** Local Waves
0–4 are implementation plus local gates only — not live production conformance.

## Progress scoreboard

| Wave | Local forge status | Remaining for true DoD |
| --- | --- | --- |
| 0 | CLEAN / contract locked | Live deploy conformance UNKNOWN |
| 1 | CLEAN locally (auth, commerce, usage, login return, product destinations) | portal_refresh + email codes still in-memory; prod-shaped durability |
| 2 | CLEAN locally (hosted jobs, server-managed artifacts, audio cleanup) | device-key wrapping deferred; separate worker process; live canary |
| 3 | CLEAN locally (devices, sync, revoke, desktop states) | recovery crypto (501); sync export/delete; Keychain |
| 4 | LOCAL PROOF (quarantine + readiness doc + broad gates) | push, canary, migration counts, live discovery HTTPS, human release |

**Local branch tips (not pushed):** dictate `forge/dictate-pro-platform` @ `1423030`;
arc-forge-deck `forge/wave1-durable-auth` @ `965fe40`.

Ship one coherent, production-ready Dictate product: local Dictate works without
an account; Arc Forge provides neutral identity, commerce, entitlements,
devices, encrypted sync, hosted transcription, and usage accounting; Dictate
Pro is the paid Dictate entitlement, not a separate identity or product.

This file controls cross-system decisions. `TRANSCRIPTION_PLAN.md`,
`DICTATE_PRO_CLOUD_SYNC_PLAN.md`, and
`deck-sections-and-dictate-space-spec.md` are subordinate implementation inputs.

## Definition of done

- One neutral Arc Forge login works across products and returns users to
  Dictate—not an agent-first Deck screen.
- Local Dictate remains complete and private without an account or working Arc
  Forge services.
- Desktop auth, refresh, revocation, devices, sync, hosted jobs, and usage
  survive restarts and rolling deploys.
- Dictate Pro commerce and entitlement state has one authority and one policy.
- Hosted transcription uses server-side credentials, product capability checks,
  exact-once audio-second accounting, durable workers, bounded audio retention,
  and server-managed encrypted hosted results.
- Sync is explicitly enabled, client-side encrypted, multi-device capable,
  recoverable, revocable, exportable, and deletable.
- Production code, deployment, tests, copy, and current documentation describe
  the same system; superseded paths and documents are removed or archived.

## Non-negotiable boundaries

1. `PortalAccount.account_id` is the identity and ownership boundary. Stripe IDs
   are billing references. Public desktop clients have no client secret.
2. Dictate is the product; `dictate_pro` is its entitlement. Deck and Dictate
   share platform primitives but retain separate product spaces and usage
   ledgers.
3. Dictate owns desktop/local UX, local secrets, sync and hosted-job clients,
   packaging, compatibility, and product tests. The shared backend owns account
   identity, grants, devices, commerce, entitlements, provider credentials,
   usage policy, workers, and production APIs. Deck owns Deck UI and semantics.
4. Provider keys, auth tokens, audio, readable transcripts, hotwords, dictated
   text, and signed upload URLs never enter logs, analytics, sync records, or
   support exports. Provider keys never reach clients.
5. Login never enables sync. Sync is explicit and encrypted before upload. Raw
   audio is only sent for an explicit hosted job and is deleted on terminal
   outcome or TTL. Readable results are not retained after bounded delivery.
6. Refresh families and single-use grants are durable, hashed, atomic, rotated,
   replay-detecting, expiring, and revocable by device/account/family.
7. `/v1` remains a labelled local/reference or bounded legacy surface. The
   canonical production client uses `/api`; interim production authorities are
   migrated or removed.
8. Do not redesign Deck, create a second account/commerce/gateway authority, or
   make cloud features mandatory for local Dictate.

## Execution model — build fast, review at milestones

The default loop optimizes for implementation throughput:

1. **Luna builds the whole current wave.** Give it the outcome, constraints,
   existing evidence, and exact acceptance commands. Keep the same Luna session
   for fixes. Avoid discovery-only rounds and tiny commit-by-commit delegation.
2. **The conductor reviews quickly after each coherent batch.** Inspect the
   diff, compare it with this file and source truth, run scoped tests/builds,
   and return only concrete P0–P2 findings with expected outcomes. Do not repeat
   broad repository archaeology once evidence is recorded.
3. **Luna fixes accepted findings immediately.** Re-run only affected gates,
   then continue the wave. Commit coherent green milestones, not every small
   correction.
4. **Deep review happens after a wave is implementation-complete and conductor-
   green.** Sol receives a fresh read-only snapshot. It does not review drafts,
   partial inventories, or every intermediate commit.
5. **Fix once, re-review once.** Route accepted Sol findings back to the same
   Luna session. A fresh Sol pass verifies the completed fix set. Escalate only
   unresolved P0–P2 findings or a genuine external decision.
6. Run the broad integration/release suite once at final closeout. During build
   waves, use the smallest gate that proves the changed surface.

Review evidence must be concise: finding, severity, `file:line`, impact, and
required outcome. Status narration and repeated diff dumps are not deliverables.

## Attack plan

### Wave 0 — Lock the contract, then stop planning

The Dictate-side inventory, contract, and backend handoff already exist:

- [Platform contract v1](contracts/dictate-platform-v1.json)
- [Platform inventory v1](platform/dictate-platform-inventory-v1.md)
- [Backend handoff v1](platform/arc-forge-backend-handoff-v1.md)

Resolve only decisions that change implementation: canonical origin/routes,
shared-backend owner, data authorities, and external repository coordination.
Record unknown deployment facts as verification tasks; do not block independent
Dictate-side work or expand the planning pack.

Gate: every production surface has one proposed authority and no unresolved
decision prevents Wave 1 implementation.

Status: **PASSED — planning authority lock only.** The linked contract,
inventory, and handoff assign one proposed authority per production surface;
deployment facts remain **UNKNOWN** later verification tasks. No live
conformance or Wave 1 implementation is claimed in this status.

### Wave 1 — Durable account, login, commerce, and usage

Build as one backend milestone:

- Replace process-memory grants/refresh state with durable hashed stores,
  atomic consumption, rotation, retry grace, replay detection, cleanup, and
  revocation.
- Enforce token type/audience, PKCE, device authorization, CSRF, exact redirect
  validation, safe continuation, rate limits, and canonical HTTPS discovery.
- Make the login/account shell Arc Forge-neutral and return every supported
  login method to the initiating Dictate flow.
- Establish the Dictate product destination for plan, usage, billing, devices,
  sync/recovery, downloads, export, and cloud deletion.
- Consolidate Stripe/webhook, commerce, entitlement, and policy states into one
  authority; legacy Dictate rows bridge one-way into commerce (no dual-read gates).
- Implement immutable Dictate usage events and balances with reservation,
  measured settlement, rollback, idempotency, constraints, and reconciliation.

Gate: login and refresh survive restart/rolling deploy; all login methods return
to Dictate; commerce and usage answers agree across backend, portal, and client.

Status: **IMPLEMENTED LOCALLY — CLEAN** on forge branches (Waves 1 R1–R2). Durable
hashed auth/commerce/usage, neutral login return, and product destinations are
local-green; `portal_refresh` and email codes remain in-process-memory interim.
**Not deployed.**

### Wave 2 — Governed hosted transcription

Build the complete hosted lane:

- Put Dictate STT behind the shared account/product/capability, provider policy,
  secret, telemetry, budget, timeout/retry, idempotency, and error contract.
- Keep audio-second semantics separate from Deck usage. Clients request a
  Dictate capability, never a provider/model credential.
- Implement the canonical job lifecycle: created, awaiting upload, uploaded,
  queued, processing, completed, failed, cancelled, expired, quota rejected.
- Use constrained signed uploads and durable queue/worker processing.
- Meter exactly once; make retries and completion idempotent.
- Deliver server-managed encrypted result artifacts with authenticated retrieval,
  acknowledgement, expiry, deletion, and account isolation.
- Delete audio on success, failure, cancellation, or TTL in every storage mode.

Gate: desktop-to-provider-fixture-to-result works across restart, retry, lost
response, duplicate completion/retrieval, quota failure, provider failure,
cross-account attempts, and cleanup.

Status: **IMPLEMENTED LOCALLY — CLEAN** on forge branches (Waves 2 R1–R3).
Governed hosted jobs, server-managed encrypted artifacts, and audio cleanup are
local-green; device-key wrapping deferred, separate worker process, and live
canary remain open. **Not deployed.**

### Wave 3 — Devices, encrypted sync, and desktop convergence

Finish the user-facing product:

- Bind devices, refresh families, sync, and hosted authorization so revocation
  has one predictable effect.
- Complete first/additional device approval, recovery, reinstall, revoke,
  export, cloud delete, offline outbox, cursor, conflict, and isolation flows.
- Keep account and device private keys in the OS secret store; the server sees
  only public keys and encrypted envelopes/content.
- Present Local, signed-in Arc Forge, and explicitly enabled Dictate Pro cloud
  states clearly. Use “Local/Cloud” for execution and “Dictate Pro” only for the
  paid offering.
- Distinguish auth expiry, gateway outage, inactive entitlement, quota,
  provider failure, paused sync, and revoked device. Clear credentials only on
  definitive auth failure and preserve safe local fallback.
- Remove obsolete flags and update onboarding, Store, account, privacy, and
  support copy.

Gate: two clean installations can join, sync encrypted records, recover,
revoke, export, and delete; users can always predict what leaves the device and
local Dictate stays usable during a total platform outage.

Status: **IMPLEMENTED LOCALLY** on forge branches (Waves 3 R1–R2). Recovery approve
is fail-closed (`501`); export/delete deferred. **Not deployed.**

### Wave 4 — Integrate, migrate, release, and delete interim architecture

- Test in a production-shaped environment using the real proxy, database,
  object storage, worker, and secret-delivery model.
- Run contract, integration, security, privacy, migration, rollback, packaging,
  and desktop/UI suites; canary with internal then small opt-in cohorts.
- Reconcile migrated accounts, subscriptions, sessions, devices, usage, jobs,
  portal links, and old client compatibility with explicit counts.
- Prove gateway/provider disable rollback and safe desktop local fallback.
- Remove process-memory auth, redundant Console/Deck URLs, dual commerce reads,
  exceptional provider paths, obsolete sign-in flags, production claims in the
  reference server, and superseded current-plan documents.
- Align privacy policy, terms, deployment security, support runbooks, release
  metadata, and live behavior.

Gate: no open P0/P1 security, privacy, billing, cross-account, data-loss, or
provider-secret finding; canary metrics and reconciliation are clean; rollback
is proven; existing clients have a bounded compatibility path; stable artifacts
are reproducible and ready for explicit human release approval.

Status: **LOCAL PROOF — Rounds 1–3** — `goal.md` scoreboard refreshed, residual
auth quarantined, tip-SHA honesty across readiness/handover, broad pytest gates
run. Push/deploy/canary/migration counts/live discovery HTTPS remain **out of
scope** until explicit human go. See
[forge-wave4-release-readiness-2026-07-12.md](forge-wave4-release-readiness-2026-07-12.md).

## Required final proof

The final evidence pack must cover:

- identity merge/isolation and every login, cancellation, replay, and return path;
- grant/refresh durability, concurrency, expiry, and revocation;
- Stripe-to-entitlement and job-to-usage reconciliation;
- provider allowlists, budgets, failure/timeout, redaction, and account isolation;
- hosted upload, restart, retry, encrypted delivery, and audio/result deletion;
- explicit sync consent, two-device encryption, conflict, recovery, revoke,
  export, deletion, and offline behavior;
- local-only operation and safe behavior through partial and total outages;
- migration counts, legacy redirects, rollback, packaging, and release SHA.

Completion means the intended architecture is live and proven—not merely that
sign-in works or one transcription succeeds.
