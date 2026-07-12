# Arc Forge Backend Handoff v1

**Status:** PENDING OWNER CONFIRMATION.

**Phase 0 gate:** **PENDING — not passed.** This handoff is the smallest
Dictate-side request to the external active `arc-forge-deck` owner. It does not
claim that source implementation or live routes conform to the
[Dictate Platform Contract v1](../contracts/dictate-platform-v1.json).

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

## Smallest requested backend changes

1. **Canonical account discovery and login.** Confirm one neutral Arc Forge
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
   audio or readable transcript text into normal sync data.

6. **Durable hosted job handoff.** Make create/upload/status/result/ack/cancel
   worker-owned and restart-safe. Completion must persist before the worker
   responds; client polling must find the same owner-bound encrypted artifact
   after a lost response; retrieval and acknowledgement must be idempotent;
   raw audio and readable result material must expire and be deleted after the
   tested lifecycle.

7. **Governed gateway and exact usage.** Route Dictate capabilities
   `dictate.transcribe` and `dictate.transcribe_diarized` through one agreed
   server-side gateway boundary. Each immutable usage event must carry
   `event_id`, `account_id`, product/capability, request/job/idempotency and
   correlation identifiers, period, event type, lifecycle, numeric amount and
   quantity in `audio_seconds`, and enough linkage for reserve, settle, and
   rollback.

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
route map. The external owner must confirm that map as a whole, including the
following operation groups and their HTTPS origin; this handoff does not create
a second machine-readable route map.

| Surface | Contract operation IDs | Owner decision |
| --- | --- | --- |
| Discovery/login/token/refresh | `account.discovery`, `account.login_authorize`, `account.token`, `account.device_authorize` | Issuer/origin, HTTPS advertisement, PKCE, device grant, refresh rotation/reuse, and neutral Arc Forge return behavior |
| Entitlement and commerce | `entitlement.read`, `commerce.read` | Shared account read authority, product filter, plan/state mapping, and Stripe projection |
| Devices | `device.register`, `device.list`, `device.approve`, `device.revoke` | Device key binding, approval, revocation propagation, and account isolation |
| Encrypted sync | `sync.push`, `sync.pull`, `sync.cursor`, `sync.key_envelopes.write`, `sync.key_envelopes.read`, `sync.export`, `sync.delete` | Opt-in, envelope encryption, cursor/conflict semantics, export, and cloud deletion |
| Hosted jobs | `hosted.create`, `hosted.upload`, `hosted.status`, `hosted.result`, `hosted.ack`, `hosted.cancel` | Durable worker, upload/processing TTL, owner-bound encrypted result, retry/ack/delete semantics |
| Shared gateway | `gateway.invoke` | Internal-only transport, provider policy, normalized errors, and usage ledger ownership |

The current source route candidates are visible at
`arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12807-12855` and
`arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1329-1638`; they require
reconciliation with the contract and are not deployed-route proof.

## Surface-specific privacy data-flow matrix

This matrix is an acceptance contract, not a prose aspiration.

| Surface | Allowed surfaces | Forbidden surfaces | Lifetime/proof requirement |
| --- | --- | --- | --- |
| Provider credentials and server client secrets | Server runtime secret boundary only | Desktop client, browser payload, sync, logs, analytics, support exports | Never client-visible; no public-native client secret |
| Access/refresh/auth/device tokens | Auth protocol and secure native storage only | Logs, sync, support exports, analytics, provider requests | Protocol TTL, refresh rotation/revocation, and OS-backed storage |
| Hosted audio | Explicit hosted upload and bounded processing worker | Normal sync, logs, analytics, support exports | Upload/processing TTL; delete on terminal outcome or expiry |
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

## Pending owner confirmation

The Phase 0 gate remains **PENDING** until the external active owner provides a
versioned response confirming:

- the canonical Arc Forge origin and the single contract operation map;
- the owner role and source/deployment status for account, commerce,
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
Dictate-side planning inputs only. Phase 1 implementation must not begin from
this handoff alone.
