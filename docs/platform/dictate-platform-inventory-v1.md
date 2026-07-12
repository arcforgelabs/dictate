# Dictate Platform Inventory v1

**Status:** Wave 0 authority lock — Dictate-side inventory only; planning gate passed, deployment verification remains UNKNOWN.

**Snapshot:** Dictate branch `forge/dictate-pro-platform` at the current Wave 0
implementation snapshot. The client source split below is source-verified.
Shared backend source evidence is pinned to
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
| Local/reference auth stores | `src/dictate/pro/auth.py:86-162,164-385`; `src/dictate/pro/store.py:186-255,1096-1302` (`auth_challenges`, authorization/device codes, token rows) | Dictate implementation lane | SQLite-backed reference auth, email-code, PKCE, refresh, and RFC device-code source is present; it is not the shared identity authority | Not applicable as a production deployment | Test/reference harness; migration input for protocol behavior |
| Local/reference commerce, usage, and transcript stores | `src/dictate/pro/service.py:58-64,82-147,408-419,607-620,637-702`; `src/dictate/pro/store.py:255-345,1512-1805`; `src/dictate/pro/stripe_handler.py:61-189` | Dictate implementation lane | Reference subscription, usage-period/event, job, segment, and Stripe webhook source is present; local transcript persistence intentionally stores segment metadata without readable text | Not applicable as a production deployment | Test/reference harness; migration input for product semantics and usage lifecycle |
| Local provider/browser flags | `src/dictate/pro/server.py:35-64,196-205,236-243,387-437`; `src/dictate/pro/relay.py:27-92`; `src/dictate/pro/browser_auth.py:22-112`; `src/dictate/pro/client.py:782-788` | Dictate implementation lane | Reference `DICTATE_PRO_*` auto-approval/provider flags and browser/device helpers are source-present; client routing selects `/api` for non-loopback and `/v1` only for local/explicit legacy | Not applicable as a production deployment | Test/reference and compatibility input; remove provider/approval shortcuts from production |
| Arc Forge account identity | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:100-112` (`PortalAccount.account_id`) | External active shared backend owner | Source implementation present at the pinned revision | **UNKNOWN**; no live revision evidence supplied | Production authority candidate |
| Shared entitlement and commerce projections | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:363-375` (`Entitlement`); `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:409-431` (`CommerceSubscription`) | External active shared backend owner | Source implementation present and shared-product shaped | **UNKNOWN** | Production authority candidate |
| Dictate subscription and usage models | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:434-480` (`DictateSubscription`, `DictateUsagePeriod`, `DictateUsageEvent`) | External active shared backend owner | Source implementation present; current usage event has `event_id`, `account_id`, `job_id`, `billable_seconds`, and `period_start`, but not the v1 amount/quantity, lifecycle, idempotency, and correlation contract | **UNKNOWN** | Migration input |
| Dictate job, upload, and transcript models | `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:483-540` (`DictateJob`, `DictateUpload`, `DictateTranscriptSegment`) | External active shared backend owner | Source implementation present, including job status, upload expiry/storage kind, and plaintext segment text | **UNKNOWN** | Production authority candidate with migration risks |
| Dictate backend route implementation | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1329-1435,1437-1460,1460-1638` (`build_dictate_router`, entitlement/usage/jobs/upload/audio/transcript routes) | External active shared backend owner | Source implementation present at the pinned revision; it is not the v1 contract implementation claim | **UNKNOWN** | Migration input |
| Shared desktop auth router and app wiring | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12807-12855` (`build_account_auth_router`); `arc-forge-deck@2ee29c9:src/arc_forge_console/main.py:312-320` | External active shared backend owner | Source routes include login-code, verify-code, token, and device-code; app includes the auth and Dictate routers | **UNKNOWN**; live probes do not identify a source revision | Production authority candidate with durability gate |
| Pinned discovery, email fallback, and token authority | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12807-12890,11965-12080,12106-12275` | External active shared backend owner | **SUPERSEDED (forge overlay):** Dictate desktop OAuth/device/refresh durable in `DurableAuthStore`; email login-code still residual interim | **UNKNOWN**; deployed revision and restart behavior are unverified | Wave 1 local proof; email-code durability residual |
| Pinned browser consent and device consent/approval | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12892-13123` (`/auth/authorize` and full approval handler); `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12632-12802` (`/deck/link` and full approval handler); device issuance `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12822-12872` | External active shared backend owner | Session/CSRF-bound browser consent and signed-in device user-code approval source is present | **UNKNOWN**; live approval behavior and canonical route exposure are unverified | Production authority candidate; canonical-route and privacy verification task |
| Pinned commerce projection, checkout, and webhook dispatch | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:201-348,1228-1400`; `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:13125-13127,20548-20550`; Stripe dispatch `arc-forge-deck@2ee29c9:src/arc_forge_console/main.py:160-200` | External active shared backend owner | Shared commerce read, Dictate checkout/entitlement, and product-line-gated Stripe lifecycle dispatch source is present; canonical v1 state/lifecycle contract still requires migration | **UNKNOWN**; no deployed revision or webhook delivery proof | Production authority candidate; commerce reconciliation and `canceled` mapping verification task |
| Auth grant and refresh state | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:206-257` (`_dictate_auth_codes`, `_dictate_device_codes`, `_dictate_device_codes_by_user_code`, `_refresh_tokens`); token logic `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:12106-12268` | External active shared backend owner | **SUPERSEDED (forge overlay):** desktop grants/refresh in `DurableAuthStore`; browser `_refresh_tokens` + `portal_refresh` remain residual interim | **UNKNOWN** | See `residual_interim_auth.py` |
| Hosted audio storage | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:717-764` (`local_spool`); `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:767-828` (`signed_object_upload`) | External active shared backend owner | Both local spool and signed object upload source paths exist, with TTL fields and cleanup hooks | **UNKNOWN** | Migration input; raw-audio lifecycle must be proven |
| Hosted worker/request mode | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:961-1121` (processing); `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1124-1163` (`run_dictate_upload_background`); request scheduling `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1517-1523,1552-1629` | External active shared backend owner | Both background-task and request-thread processing paths exist | **UNKNOWN**; worker restart/lost-response behavior is unverified | Migration input |
| Hosted transcript handoff | `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:831-880` writes segment text; `arc-forge-deck@2ee29c9:src/arc_forge_console/dictate.py:1197-1225` returns readable transcript text; `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:526-540` stores `text` | External active shared backend owner | **SUPERSEDED (forge overlay):** server-managed encrypted `DictateResultArtifact` is authoritative hosted result path; legacy transcript routes may remain for compatibility | **UNKNOWN** | Wave 2 local proof — server-managed encrypted artifact |
| Direct Dictate provider path | `arc-forge-deck@2ee29c9:src/arc_forge_console/config.py:161-175` (`DICTATE_XAI_*`, `LITELLM_*`); `arc-forge-deck@2ee29c9:src/arc_forge_console/provider_gateway.py:61-71,239-282` reads the xAI credential and posts directly to `api.x.ai` | External active shared backend owner | Direct xAI STT source path exists; the shared LiteLLM path is not proven for Dictate audio | **UNKNOWN** | Migration risk: provider access must move behind the agreed governed gateway boundary |
| Shared LiteLLM tooling | `arc-forge-deck@2ee29c9:src/arc_forge_console/litellm_gateway.py:83-118,148-240` builds virtual-key policy and a Deck chat-completion probe | External active shared backend owner | Existing policy/probe source is present, but it is not evidence of a Dictate audio production contract | **UNKNOWN** | Migration input; no second gateway authority |
| Database/session lane | `arc-forge-deck@2ee29c9:src/arc_forge_console/database.py:23-32,302-315` builds the configured engine/session factory; Dictate tables are in `arc-forge-deck@2ee29c9:src/arc_forge_console/models.py:434-540` | External active shared backend owner | Source supports configured SQLite/PostgreSQL engines and creates the listed tables | **UNKNOWN**; database reachability and deployed schema are not verified | Production authority candidate with migration gate |
| Proxy/origin header lane | `arc-forge-deck@2ee29c9:src/arc_forge_console/dashboard.py:2055-2104` filters and sets trusted proxy headers; `arc-forge-deck@2ee29c9:src/arc_forge_console/main.py:111-113,299-301` handles forwarded client/origin allowlists | External active shared backend owner | Source proxy/origin handling is present; HTTPS scheme, host routing, and Dictate return behavior require live verification | **UNKNOWN**; supplied probes advertise HTTP endpoints and Deck root branding | Migration input; canonical origin/proxy verification task |
| Release/deployment lane | `arc-forge-deck@2ee29c9:.github/workflows/ci-deploy.yml:211-245,257-301,352-425`; `arc-forge-deck@2ee29c9:src/arc_forge_console/release.py:9-19` emits release metadata | External active shared backend owner | Source pipeline can build/tag/deploy images and expose a release SHA, subject to operator workflow | **UNKNOWN** for the Dictate routes; no deployed image SHA was verified | Migration input; release proof required |
| Live desktop discovery probes | Supplied 2026-07-11 evidence: `https://console.arcforge.au/api/account/auth/desktop` and `https://deck.arcforge.au/api/account/auth/desktop` return `200` but advertise `http://` endpoints; public roots resolve to `/deck/login` with title `Deck` | External deployed-service owner | Live behavior observed, but not revision-resolvable from this repository snapshot | **UNKNOWN** revision; observed behavior fails the future HTTPS/neutral-branding gate | Migration input |
| Forge LLM gateway repository | Supplied evidence: `/home/samuel/repos/forge-llm-gateway` is 311 commits behind `origin` | No owner authority for this work | Not an authority candidate for this contract | Not applicable | Dead/excluded |
| Dictate-side contract and handoff | `docs/contracts/dictate-platform-v1.json`; `docs/platform/arc-forge-backend-handoff-v1.md` in this branch | Dictate implementation lane → external shared backend owner | Versioned Wave 0 authority/contract artifacts lock one proposed authority per production surface; no live conformance is claimed | Not deployed; **UNKNOWN** | Migration input and later deployment-verification task |

## Forge local implementation overlay (2026-07-12)

Local forge branches supersede several pinned `2ee29c9` inventory rows for
**source implementation** (not deployment):

| Surface | Local branch | Tip evidence | Deploy status |
| --- | --- | --- | --- |
| Durable desktop auth | `forge/wave1-durable-auth` | `DurableAuthStore`, `test_durable_auth.py` | **NOT DEPLOYED** |
| Single commerce authority | `forge/wave1-durable-auth` | `_ensure_canonical_dictate_commerce` — no dual-read gates | **NOT DEPLOYED** |
| Hosted encrypted results | `forge/wave1-durable-auth` | `DictateResultArtifact`, `test_dictate_hosted_jobs.py` | **NOT DEPLOYED** |
| Devices + sync | `forge/wave1-durable-auth` | `dictate_devices.py`, `dictate_sync.py`, `test_dictate_devices_sync.py` | **NOT DEPLOYED** |
| Desktop convergence | `forge/dictate-pro-platform` | `platform_state.py`, `test_platform_state.py` | **NOT DEPLOYED** |

Residual interim auth (`_login_codes`, companion `_auth_codes`, `portal_refresh`)
is documented in `arc_forge_console/residual_interim_auth.py` and must not be
described as production-durable Dictate desktop auth.

Hosted transcript handoff at the pinned revision stored plaintext segments.
Local forge implementation delivers server-managed encrypted artifacts; legacy
transcript routes may remain for compatibility but are not the authoritative
hosted result path.

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

## Wave 0 gate status

**PASSED — planning authority lock only.** Every production surface has one
proposed authority and the contract, source-flow manifest, and handoff expose no
unresolved implementation decision that blocks Wave 1. Source implementation
status is separated from deployment verification; all unverified external/live
facts remain explicit **UNKNOWN** later tasks. Durable auth, governed gateway,
encrypted handoff, usage enforcement, and live release proof are Wave 1–4
implementation/release gates, not claims of this inventory.
