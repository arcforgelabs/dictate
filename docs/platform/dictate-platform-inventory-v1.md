# Dictate Platform Inventory v1

**Status:** Phase 0 evidence pack — Dictate-side inventory only.

**Snapshot:** Dictate branch `forge/dictate-pro-platform` at `48b4c7c` before
this Round 2 fix. The client source split below was already present in the
`9e4dcf5` source baseline. Shared backend source evidence is pinned to
`arc-forge-deck@2ee29c9dbefb5208aea331042f56b8fad7112b4f`; the deployed
revision is **UNKNOWN**. Source presence is not a deployment claim.

**Authority:** [the cross-system goal](../goal.md) and the single canonical
operations map in the machine-readable [Dictate Platform Contract v1](../contracts/dictate-platform-v1.json).

## Disposition vocabulary

| Disposition | Meaning |
| --- | --- |
| Production authority candidate | Source appears to own the responsibility, but owner confirmation and deployment verification are still required. |
| Compatibility path | Existing client or route retained while canonical production routes are agreed and migrated. |
| Test/reference harness | Useful for local tests or shape discovery; not a production authority. |
| Migration input | Evidence or implementation that must be reconciled, replaced, or promoted. |
| Dead/excluded | Not an authority for this work and must not be revived implicitly. |

## Authority and disposition table

The columns intentionally separate the person/team role, what exists in the
source revision, whether a deployed revision was verified, and the disposition
for this Dictate work.

| Surface | Evidence | Owner role | Source implementation status | Deployment verification status | Disposition |
| --- | --- | --- | --- | --- | --- |
| Current desktop `/api` gateway compatibility | `src/dictate/pro/client.py:162-196,451-498,703-788,895-901`; focused route tests in `tests/test_pro_client.py:221-383` | Dictate implementation lane | Implemented and source-tested: non-loopback URLs and explicit `arcforge/gateway/hosted` modes use `/api`; local/explicit `local/legacy` modes use `/v1` | **UNKNOWN**; source tests do not verify a released service | Compatibility path |
| Local/explicit legacy `/v1` reference | `src/dictate/pro/server.py:196-205,327-437,559-582` | Dictate implementation lane | Implemented as a local/reference HTTP harness with `/v1` auth, devices, sync, and meetings | Not applicable as a production deployment; no released-client count is claimed | Test/reference harness |
| Arc Forge account identity | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:100-112` (`PortalAccount.account_id`) | External active shared backend owner | Source implementation present at the pinned revision | **UNKNOWN**; no live revision evidence supplied | Production authority candidate |
| Shared entitlement and commerce projections | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:363-375` (`Entitlement`); `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:409-431` (`CommerceSubscription`) | External active shared backend owner | Source implementation present and shared-product shaped | **UNKNOWN** | Production authority candidate |
| Dictate subscription and usage models | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:434-480` (`DictateSubscription`, `DictateUsagePeriod`, `DictateUsageEvent`) | External active shared backend owner | Source implementation present; current usage event has `event_id`, `account_id`, `job_id`, `billable_seconds`, and `period_start`, but not the v1 amount/quantity, lifecycle, idempotency, and correlation contract | **UNKNOWN** | Migration input |
| Dictate job, upload, and transcript models | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:483-540` (`DictateJob`, `DictateUpload`, `DictateTranscriptSegment`) | External active shared backend owner | Source implementation present, including job status, upload expiry/storage kind, and plaintext segment text | **UNKNOWN** | Production authority candidate with migration risks |
| Dictate backend route implementation | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1329-1435,1437-1460,1460-1638` (`build_dictate_router`, entitlement/usage/jobs/upload/audio/transcript routes) | External active shared backend owner | Source implementation present at the pinned revision; it is not the v1 contract implementation claim | **UNKNOWN** | Migration input |
| Shared desktop auth router and app wiring | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12807-12855` (`build_account_auth_router`); `arc-forge-deck@2ee29c9:src/arc_forge_console/main.py:312-320` | External active shared backend owner | Source routes include login-code, verify-code, token, and device-code; app includes the auth and Dictate routers | **UNKNOWN**; live probes do not identify a source revision | Production authority candidate with durability gate |
| Auth grant and refresh state | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:206-257` (`_dictate_auth_codes`, `_dictate_device_codes`, `_dictate_device_codes_by_user_code`, `_refresh_tokens`); token logic `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12106-12268` | External active shared backend owner | Process-memory stores and pop/rotate logic are present; restart/deploy durability is not established | **UNKNOWN** | Migration input; durable-auth risk |
| Hosted audio storage | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:717-764` (`local_spool`); `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:767-828` (`signed_object_upload`) | External active shared backend owner | Both local spool and signed object upload source paths exist, with TTL fields and cleanup hooks | **UNKNOWN** | Migration input; raw-audio lifecycle must be proven |
| Hosted worker/request mode | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:961-1121` (processing); `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1124-1163` (`run_dictate_upload_background`); request scheduling `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1517-1523,1552-1629` | External active shared backend owner | Both background-task and request-thread processing paths exist | **UNKNOWN**; worker restart/lost-response behavior is unverified | Migration input |
| Hosted transcript handoff | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:831-880` writes segment text; `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1197-1225` returns readable transcript text; `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:526-540` stores `text` | External active shared backend owner | Plaintext transcript persistence/delivery exists in source | **UNKNOWN** | Migration risk: replace with owner-bound encrypted artifact and bounded plaintext lifecycle |
| Direct Dictate provider path | `arc-forge-deck@2ee29c9:src/arc_forge_console/config.py:161-175` (`DICTATE_XAI_*`, `LITELLM_*`); `arc-forge-deck@2ee29c9:src/arc_forge_console/provider_gateway.py:61-71,239-282` reads the xAI credential and posts directly to `api.x.ai` | External active shared backend owner | Direct xAI STT source path exists; the shared LiteLLM path is not proven for Dictate audio | **UNKNOWN** | Migration risk: provider access must move behind the agreed governed gateway boundary |
| Shared LiteLLM tooling | `arc-forge-deck@2ee29c9:src/arc_forge_console/litellm_gateway.py:83-118,148-240` builds virtual-key policy and a Deck chat-completion probe | External active shared backend owner | Existing policy/probe source is present, but it is not evidence of a Dictate audio production contract | **UNKNOWN** | Migration input; no second gateway authority |
| Database/session lane | `arc-forge-deck@2ee29c9:src/arc_forge_console/database.py:23-32,302-315` builds the configured engine/session factory; Dictate tables are in `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:434-540` | External active shared backend owner | Source supports configured SQLite/PostgreSQL engines and creates the listed tables | **UNKNOWN**; database reachability and deployed schema are not verified | Production authority candidate with migration gate |
| Release/deployment lane | `arc-forge-deck@2ee29c9:.github/workflows/ci-deploy.yml:211-245,257-301,352-425`; `arc-forge-deck@2ee29c9:src/arc_forge_console/release.py:9-19` emits release metadata | External active shared backend owner | Source pipeline can build/tag/deploy images and expose a release SHA, subject to operator workflow | **UNKNOWN** for the Dictate routes; no deployed image SHA was verified | Migration input; release proof required |
| Live desktop discovery probes | Supplied 2026-07-11 evidence: `https://console.arcforge.au/api/account/auth/desktop` and `https://deck.arcforge.au/api/account/auth/desktop` return `200` but advertise `http://` endpoints; public roots resolve to `/deck/login` with title `Deck` | External deployed-service owner | Live behavior observed, but not revision-resolvable from this repository snapshot | **UNKNOWN** revision; observed behavior fails the future HTTPS/neutral-branding gate | Migration input |
| Forge LLM gateway repository | Supplied evidence: `/home/samuel/repos/forge-llm-gateway` is 311 commits behind `origin` | No owner authority for this work | Not an authority candidate for this contract | Not applicable | Dead/excluded |
| Dictate-side contract and handoff | `docs/contracts/dictate-platform-v1.json`; `docs/platform/arc-forge-backend-handoff-v1.md` in this branch | Dictate implementation lane → external shared backend owner | Versioned planning artifacts only; owner confirmation is pending | Not deployed; **UNKNOWN** | Migration input |

## Current/reference state mapping

The custom contract records reusable enum definitions and maps source values
explicitly. In particular, current backend `ready` maps to canonical hosted
job `completed`; `quota_exceeded` maps to `quota_rejected`. The local/reference
server keeps `queued`, `processing`, `ready`, `failed`, and `quota_exceeded`
as reference values only. No source status is treated as proof of deployed
canonical behavior.

## Live evidence notes

The live observations above are recorded as supplied evidence for 2026-07-11;
this round does not mutate or authenticate to any live system. No credentials,
tokens, provider keys, audio, transcript, or user data are included here.

The `200` responses are not treated as proof of production correctness. The
advertised insecure URLs and Deck-branded `/deck/login` landing behavior remain
open migration findings for the shared owner.

## Phase 0 gate status

**PENDING — not passed.** The inventory distinguishes source implementation,
owner role, and deployment verification. Owner confirmation, canonical route
agreement, durable auth, governed gateway ownership, encrypted result handoff,
quantity-bearing usage events, and live release proof remain outstanding.
