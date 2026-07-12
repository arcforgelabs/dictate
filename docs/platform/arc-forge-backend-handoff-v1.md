# Arc Forge Backend Handoff v1

**Status:** WAVE 0 AUTHORITY LOCKED — DEPLOYMENT VERIFICATION UNKNOWN.

**Wave 0 gate:** **PASSED — planning authority lock only.** This handoff is the smallest
Dictate-side request to the external active `arc-forge-deck` owner. It does not
claim that source implementation or live routes conform to the
[Dictate Platform Contract v1](../contracts/dictate-platform-v1.json).
External owner response, deployment SHA, and live behavior remain later
verification tasks and do not leave an implementation decision unresolved for
independent Wave 1 work.

## Repository boundary and evidence status

Dictate implementation stays in `/home/samuel/repos/dictate` on
`forge/dictate-pro-platform`. Shared account, commerce, backend, Deck
stabilization, deployment, and release ownership remains outside this lane in
`/home/samuel/repos/arc-forge-deck`. This round makes no external-repository,
Helm, live-system, or credential changes.

The external source snapshot supplied for review is
`arc-forge-deck@2ee29c9dbefb5208aea331042f56b8fad7112b4f` on
`agent/deployment-harmony-phase2`. The source implementation status is
**present at that revision**; deployment verification is **UNKNOWN**. The
release workflow's ability to emit a SHA is not evidence that these Dictate
routes are deployed at that SHA.

| Area | Dictate branch owns | Shared backend / Deck owner owns |
| --- | --- | --- |
| Desktop | Local-first UX, current `/api` gateway compatibility, local/explicit legacy `/v1` compatibility, OS secret handling, sync client, hosted-job client, packaging, and Dictate tests | — |
| Account platform | Contract fixtures, client expectations, migration notes, and evidence | Arc Forge account subject, browser sessions, desktop grants, refresh families, device authorization, canonical discovery, and return-to-Dictate behavior |
| Commerce and entitlement | Dictate product mapping and client presentation | Stripe/webhook authority, commerce projection, `product=dictate`, `entitlement=dictate_pro`, and policy states |
| Hosted gateway | Dictate capability request and audio-second consumer | Provider credential boundary, allowlists, shared middleware, STT adapter, usage event authority, and normalized errors |
| Sync and jobs | Encrypted envelopes, opt-in behavior, local outbox, polling/retrieval client, and privacy UX | Account-scoped devices, encrypted record/job APIs, durable workers, encrypted result artifacts, retention/deletion, and cross-account authorization |

## Locked proposed authority map

The contract's `authority_map` is the only machine-readable authority map. Each
production surface has one proposed authority; `UNKNOWN` below is deployment
verification status, not a second candidate or an open implementation choice.

| Production surface | One proposed authority | Owner role | Source status | Deployment verification | Disposition |
| --- | --- | --- | --- | --- | --- |
| Desktop/local compatibility | `dictate_desktop_client` | Dictate implementation lane | Source present | Not applicable | `/api` current compatibility; `/v1` local/explicit legacy only |
| Identity/auth/discovery | `arc_forge_shared_account_backend` | External shared backend owner | Pinned candidate present | **UNKNOWN** | Durable Arc Forge account, email fallback, PKCE, device grant, refresh |
| Commerce/entitlement | `arc_forge_shared_commerce_backend` | External shared backend owner | Pinned candidate present | **UNKNOWN** | Dictate checkout/webhook/projection; canonical `canceled` mapping |
| Devices/recovery | `arc_forge_shared_account_backend` | External shared backend owner | Pinned candidate present; recovery route requires migration | **UNKNOWN** | Registration, consent/approval, recovery, revocation |
| Encrypted sync | `arc_forge_shared_backend_with_dictate_client_encryption` | External shared backend + Dictate client | Contract locked; storage implementation pending | **UNKNOWN** | Client encrypts; backend owns durable envelopes/cursors |
| Hosted jobs/results | `arc_forge_shared_dictate_hosted_backend` | External shared backend owner | Pinned candidate present; artifact migration required | **UNKNOWN** | Durable worker, owner-bound authenticated artifact, ack/delete |
| Dictate usage | `arc_forge_shared_dictate_usage_ledger` | External shared backend owner | Pinned candidate present; lifecycle extension required | **UNKNOWN** | Dictate audio-second ledger, separate from Deck |
| Provider-neutral STT gateway | `arc_forge_shared_provider_gateway` | External shared backend owner | Direct provider source present; shared STT contract not proven | **UNKNOWN** | Governed provider request; server-only credentials |
| Dictate product surface | `dictate_desktop_and_dictate_product_ui` | Dictate implementation lane; Deck UI separate | Source present | Not applicable | Local/Cloud execution copy; Dictate Pro remains paid offering |

## Smallest requested backend changes

1. **Canonical account discovery and login.** Use the locked proposed origin
   `https://console.arcforge.au` and one neutral Arc Forge
   origin and make the discovery document advertise only HTTPS issuer,
   authorization, token, refresh, and device endpoints. The current live
   `console.arcforge.au` and `deck.arcforge.au` probes return `200` but
   advertise HTTP endpoints and land at Deck-branded `/deck/login`; those are
   migration evidence, not accepted production behavior.

2. **Durable desktop authentication.** Move authorization grants, device-code
   records, refresh families, replay guards, and revocation state out of
   process memory so restart and rolling deploy do not invalidate or duplicate
   authentication. The source stores are visible at
  `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:206-257` and
  token consumption/rotation at
  `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12106-12268`.

3. **One neutral identity boundary.** Make `account_id` the authenticated
   subject and ownership boundary. Keep `product=dictate` and
   `entitlement=dictate_pro` separate from the Arc Forge identity, with Dictate
   audio-second usage separate from Deck usage. Existing source candidates are
  `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:100-112,363-375,409-431`.

4. **Device authority.** Provide account-scoped register, list, approve, and
   revoke operations. A revocation must affect refresh, sync, and hosted jobs
   consistently and return the reusable device state enum from the contract.

5. **Encrypted sync authority.** Provide opt-in push/pull/cursor, key-envelope,
   export, and delete operations. The server may see only the contract's
   explicitly permitted envelope metadata and ciphertext; it must not turn raw
   audio or readable transcript text into normal sync data. Implement the
   contract's `SyncEnvelope` fields and per-record accepted/rejected/winner/
   conflict outcomes so an offline outbox can drain page by page.

6. **Durable hosted job handoff.** Make create/upload/status/result/ack/cancel
   worker-owned and restart-safe. Completion must persist before the worker
   responds; client polling must find the same owner-bound encrypted artifact
   after a lost response; retrieval and acknowledgement must be idempotent;
   raw audio and readable result material must expire and be deleted after the
   tested lifecycle. Every result is the contract's mandatory
   `HostedResultArtifact`: versioned authenticated encryption or a bounded
   artifact reference, algorithm, recipient key, nonce, account/device/job/
   artifact AAD and integrity binding, expiry, and delete-after-ack semantics.

7. **Governed gateway and exact usage.** Route Dictate capabilities
   `dictate.transcribe` and `dictate.transcribe_diarized` through one agreed
   server-side gateway boundary. Each immutable usage event must carry
   `event_id`, `account_id`, product/capability, request/job/idempotency and
   correlation identifiers, period, event type, lifecycle, numeric amount and
   quantity in `audio_seconds`, and enough linkage for reserve, settle, and
   rollback. The gateway may carry audio bytes or a bounded artifact reference
   only at the governed provider request surface; provider/model aliases are
   server-selected and credentials remain server-only.

8. **Migrate source risks before acceptance.** The pinned source has a direct
   xAI provider path and two audio-storage modes, and it persists/returns
   plaintext transcript text. These are migration findings, not claims that
  the source is deployed:
  `arc-forge-deck@2ee29c9:src/arc_forge_console/config.py:161-175,573-599`,
  `arc-forge-deck@2ee29c9:src/arc_forge_console/provider_gateway.py:61-71,239-282`,
  `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:717-828,831-880,1197-1225`,
  and `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:526-540`.

## Canonical route agreement

The machine-readable contract's root `operations` object is the only canonical
proposed route map. It is locked for independent implementation; the external
owner later verifies deployment of that map and its HTTPS origin. This handoff
does not create a second machine-readable route map.

| Surface | Contract operation IDs | Owner decision |
| --- | --- | --- |
| Discovery/email/browser/device auth | `account.discovery`, `account.email_code_start`, `account.email_code_verify`, `account.browser_consent`, `account.browser_consent_decision`, `account.token`, `account.device_authorize`, `account.device_approval` | HTTPS discovery, permanent email fallback, PKCE/browser consent, RFC device grant/polling, refresh rotation/reuse, and neutral Arc Forge return behavior |
| Entitlement, usage, and commerce | `entitlement.read`, `usage.read`, `commerce.read`, `commerce.checkout`, `commerce.webhook` | Shared account read authority, product filter, checkout/webhook projection, plan/state mapping, canonical `canceled`, and Dictate usage ledger |
| Devices and recovery | `device.register`, `device.list`, `device.approve`, `device.revoke`, `device.recovery_approve` | Device key binding, browser/device approval, current-device recovery, revocation propagation, and account isolation |
| Encrypted sync | `sync.push`, `sync.pull`, `sync.cursor`, `sync.key_envelopes.write`, `sync.key_envelopes.read`, `sync.export`, `sync.delete` | Opt-in, envelope encryption, cursor/conflict semantics, export, and cloud deletion |
| Hosted jobs | `hosted.create`, `hosted.upload`, `hosted.status`, `hosted.result`, `hosted.ack`, `hosted.cancel` | Durable worker, upload/processing TTL, inherited diarized capability, owner-bound authenticated result envelope/reference, retry/ack/delete semantics |
| Shared gateway | `gateway.invoke` | Internal-only transport, provider policy, normalized errors, and usage ledger ownership |

The current source route candidates are visible at
`arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12632-12725,12807-13007,13125-13127` and
`arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1329-1638`; they require
reconciliation with the contract and are not deployed-route proof.

## Surface-specific privacy data-flow matrix

This matrix is an acceptance contract, not a prose aspiration.

| Surface | Allowed surfaces | Forbidden surfaces | Lifetime/proof requirement |
| --- | --- | --- | --- |
| Provider credentials and server client secrets | Server runtime secret boundary only | Desktop client, browser payload, sync, logs, analytics, support exports | Never client-visible; no public-native client secret |
| Access/refresh/auth/device tokens | Auth protocol and secure native storage only | Logs, sync, support exports, analytics, provider requests | Protocol TTL, refresh rotation/revocation, and OS-backed storage |
| Hosted audio | Explicit hosted upload, bounded processing worker, and governed provider request | Normal sync, logs, analytics, support exports | Upload/processing/provider-request TTL; delete on terminal outcome or expiry |
| Governed provider-request audio | Governed server-side provider request only | Desktop provider credentials, normal sync, logs, analytics, support exports | Audio bytes or bounded artifact reference only; provider/model aliases are server-selected |
| Readable transcript | Authenticated client delivery and owner-bound encrypted result artifact | Logs, analytics, support exports, normal sync | Bounded artifact lifetime; delete after acknowledgement or TTL |

The structured version of this matrix is
`data_flow_matrix.rows` in the contract and must be used by implementation and
proof tests. The contract also requires lost-response, worker-restart,
duplicate-retrieval, retryable-ack, expiry/deletion, cross-account, and
no-readable-support/log/analytics proofs.

## Source implementation and migration risks

The pinned external source is useful evidence but is not yet the accepted
production architecture:

- `DictateJob.status` currently includes source values such as `queued`,
  `uploaded`, `processing`, `ready`, `failed`, and `quota_exceeded`; the v1
  mapping is explicitly `ready → completed` and `quota_exceeded →
  quota_rejected`.
- `DictateUsageEvent` currently has a primary event ID, account/job, billable
  seconds, and period, but not the full v1 immutable quantity/lifecycle and
  reserve-settle-rollback correlation contract.
- `local_spool` writes request audio to a path; `signed_object_upload` is an
  alternate source mode. Neither is accepted without a deletion/TTL proof.
- `DictateTranscriptSegment.text` is a plaintext source field and the current
  transcript route returns readable text. This must migrate to the bounded
  encrypted-result handoff.
- `arc-forge-deck@2ee29c9:src/arc_forge_console/provider_gateway.py:239-282`
  directly posts the Dictate audio to xAI using a server-side setting.
  `arc-forge-deck@2ee29c9:src/arc_forge_console/litellm_gateway.py:83-240`
  is currently a Deck policy/chat-completion proof, not evidence of a Dictate
  audio production lane.

## Deployment and acceptance gates

- The external owner records the accepted contract revision and deploys only
  an image whose release metadata identifies the reviewed source revision.
  The source release lane emits `git_sha`/image metadata in
  `arc-forge-deck@2ee29c9:src/arc_forge_console/release.py:9-19` and builds and
  deploys SHA-tagged images in
  `arc-forge-deck@2ee29c9:.github/workflows/ci-deploy.yml:211-245,257-301,352-425`.
  This is a gate to verify, not deployment evidence already satisfied.
- Discovery and live smoke tests show HTTPS endpoints, neutral Arc Forge
  branding, return-to-Dictate behavior, and the accepted operation map.
- Auth grants, refresh families, device records, jobs, usage events, and
  replay state survive process restart and rolling deploy.
- All account, entitlement, commerce, device, sync, hosted, gateway, and usage
  reads/writes enforce `account_id`; Dictate and Deck usage remain separate.
- Hosted jobs prove durable completion, lost-response polling, duplicate
  retrieval, idempotent acknowledgement, retry/cancel behavior, exact
  audio-second settlement/rollback, cross-account denial, and raw-audio/result
  deletion.
- Privacy tests prove the matrix above for client payloads, secure storage,
  sync, logs, analytics, support exports, provider requests, and artifacts.
- The local `/v1` server remains explicitly non-production, and no released
  `/v1` client count is claimed until an evidence source is supplied.

## Later owner and deployment verification tasks

The Wave 0 gate is **PASSED** because the proposed authorities and contract are
locked. The external active owner must still provide a versioned response and
live evidence for these later verification tasks:

- deployment of the canonical Arc Forge origin and the single contract operation map;
- the source/deployment status for account, commerce,
  entitlement, device, sync, hosted-job, gateway, and usage authorities;
- the durable store/worker/deletion design and all privacy proofs;
- the governed provider/gateway path, including whether and how existing
  LiteLLM tooling is promoted for Dictate audio;
- the source migration plan for plaintext transcript storage, direct provider
  access, current route compatibility, and the existing usage schema;
- the accepted image/source revision and live deployment verification;
- the bounded compatibility window for current `/api` clients and local or
  explicit legacy `/v1` reference behavior.

Until that confirmation exists, this document and the v1 contract are
Dictate-side authority/implementation inputs without a live-conformance claim.
This round does not begin Wave 1 or authorize external repository, deployment,
merge, or release changes.
