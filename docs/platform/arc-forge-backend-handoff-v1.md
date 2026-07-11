# Arc Forge Backend Handoff v1

**Status:** PENDING OWNER CONFIRMATION.

**Phase 0 gate:** **PENDING — not passed.** This handoff records the smallest
Dictate-side request to the external active `arc-forge-deck` owner. It does not
claim that the shared backend or live routes implement
[the Dictate Platform Contract v1](../contracts/dictate-platform-v1.json).

## Boundary and ownership

| Area | Dictate branch owns | Shared backend / Deck owner owns |
| --- | --- | --- |
| Desktop | Local-first UX, OAuth/device client, OS secret handling, sync client, hosted-job client, packaging, compatibility, and Dictate tests. | — |
| Account platform | Contract fixtures, client expectations, migration notes, and evidence. | `PortalAccount`, browser sessions, desktop grants, refresh families, device authorization, canonical discovery, and login return behavior. |
| Commerce and entitlement | Dictate product mapping and client presentation of the shared schema. | Stripe/webhook authority, commerce projection, `product=dictate`, `entitlement=dictate_pro`, and policy states. |
| Hosted gateway | Dictate capability request and audio-second usage consumer. | Provider credentials, allowlists, shared middleware, STT adapter ownership, usage event authority, and normalized errors. |
| Sync and jobs | Encrypted envelopes, opt-in behavior, local outbox, polling/retrieval client, and privacy UX. | Account-scoped devices, encrypted record/job APIs, durable workers, result artifacts, retention/deletion, and cross-account authorization. |

The shared backend and Deck stabilization owner is the external active
`/home/samuel/repos/arc-forge-deck` lane at
`agent/deployment-harmony-phase2 @ 2ee29c9`. No person's name is inferred.
This Dictate round does not modify that repository, its Helm/deployment files,
or live systems.

## Smallest requested shared changes

1. Confirm the canonical Arc Forge account origin and publish a discovery
   document whose issuer, authorization, token, refresh, and device endpoints
   are HTTPS. The current `console.arcforge.au` and `deck.arcforge.au` probes
   return `200` but advertise HTTP endpoints and land at Deck-branded
   `/deck/login`; those are migration evidence, not an accepted production
   contract.
2. Keep browser sessions, PKCE authorization codes, device codes, refresh
   families, replay guards, and revocation state durable across restart and
   rolling deploy. Store bearer-style codes hashed, rotate refresh tokens, and
   detect reuse.
3. Expose one account-scoped product schema: `account_id` is the subject and
   ownership boundary, `product` is `dictate`, and `entitlement` is
   `dictate_pro`. Keep Dictate audio-second usage separate from Deck usage.
4. Provide device registration, approval, and revocation with one effect across
   refresh, sync, and hosted jobs. Return explicit device and entitlement
   states rather than making the desktop infer them from a Deck route.
5. Provide encrypted sync envelopes and a durable hosted-job state machine.
   Hosted results must be owner-bound encrypted artifacts with idempotent
   retrieval and acknowledgement, bounded plaintext lifetime, expiry, and
   deletion after terminal processing.
6. Confirm the shared gateway owner and route Dictate capabilities
   `dictate.transcribe` and `dictate.transcribe_diarized` through one governed
   policy. Provider credentials remain server-runtime-only; usage events carry
   `account_id`, `product`, capability, request ID, and idempotency key.
7. Label the in-repo `/v1` server as test/reference-only and define the bounded
   compatibility window for current Dictate clients before changing their
   default origin or route paths.

## Canonical routes requiring owner agreement

These are proposed contract paths, not deployed claims. The origin remains
`PENDING_OWNER_CONFIRMATION` and must use HTTPS.

| Contract surface | Proposed path | Owner decision required |
| --- | --- | --- |
| Desktop discovery | `GET /api/account/auth/desktop` | Canonical account origin, issuer, and advertised endpoint scheme. |
| Login / consent | `GET /api/account/auth/authorize` | PKCE parameters, validated return-to-Dictate path, neutral Arc Forge branding, and browser-session boundary. |
| Token / refresh | `POST /api/account/auth/token` | Authorization-code and refresh grant schema, rotation, retry grace, reuse, and revocation behavior. |
| Device authorization | `POST /api/account/auth/device` | Headless fallback, approval route, expiry, replay, and device binding. |
| Entitlement / commerce | `GET /api/account/entitlements?product=dictate`; `GET /api/account/commerce?product=dictate` | Shared read authority, state mapping, Stripe/Store policy, and product/entitlement names. |
| Devices | `/api/dictate/devices` | Registration, approval, list, revoke, and account isolation. |
| Encrypted sync | `/api/dictate/sync` | Opt-in, envelope schema, cursor/conflict semantics, export, and cloud deletion. |
| Hosted jobs | `/api/dictate/jobs` | Upload, queue/worker, result retrieval/ack, idempotency, TTL, and deletion. |
| Shared gateway | Internal gateway invocation contract | Authoritative deployed gateway, LiteLLM/STT boundary, policy, errors, and usage events. |

## Deployment and acceptance gates

- The deployed discovery document advertises only canonical HTTPS URLs and the
  account flow returns to Dictate rather than an agent-first Deck page.
- Auth grants, refresh families, device records, job records, usage events, and
  required replay/rate-limit state survive restart and rolling deployment.
- No provider key, public-native client secret, audio, readable transcript,
  refresh token, or access token appears in client payloads, sync records, logs,
  or support exports.
- Entitlement, commerce, desktop state, sync authorization, hosted-job
  authorization, and reconciliation agree on `account_id`, `dictate`, and
  `dictate_pro`.
- Hosted jobs are private, restart-safe, exactly metered, retry/idempotent, and
  delete raw audio and result artifacts on the tested lifecycle.
- The `/v1` reference harness is labelled non-production and current released
  clients have a bounded compatibility and rollback path.

## Pending owner confirmation

The Phase 0 gate remains **PENDING** until the external owner confirms, in a
versioned handoff:

- the canonical Arc Forge origin and route map;
- the account, commerce, entitlement, device, sync, hosted-job, and gateway
  authorities;
- the durable store/worker/deletion design that satisfies the contract;
- the shared gateway owner and whether LiteLLM is sufficient for each lane;
- the compatibility window and migration counts for existing `/v1` clients;
- the smallest cross-repository changes and their deployment/review sequence.

Until that confirmation exists, this document and the v1 JSON contract are
Dictate-side planning inputs only. Phase 1 implementation must not begin from
this handoff alone.
