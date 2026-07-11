# Dictate Platform Inventory v1

**Status:** Phase 0 evidence pack — Dictate-side inventory only.

**Snapshot:** Dictate branch `forge/dictate-pro-platform` at `9e4dcf5` before
this Phase 0 contract/inventory commit. Shared backend evidence is recorded at
the supplied revisions; this document does not claim that the deployed backend
matches the new contract.

**Authority:** [the cross-system goal](../goal.md) and the machine-readable
[Dictate Platform Contract v1](../contracts/dictate-platform-v1.json).

## Disposition vocabulary

| Disposition | Meaning |
| --- | --- |
| Production authority | The named deployed/shared owner is authoritative for that responsibility; contract alignment is still an explicit gate. |
| Compatibility path | Existing client or route retained while canonical production routes are agreed and migrated. |
| Test/reference harness | Useful for local tests or shape discovery; not a production authority. |
| Migration input | Evidence or implementation that must be reconciled, replaced, or promoted. |
| Dead/excluded | Not an authority for this work and must not be revived implicitly. |

## Authority and disposition table

| Surface | Evidence | Owner / authority | Disposition | Phase 0 interpretation |
| --- | --- | --- | --- | --- |
| Dictate-side client and docs | Dictate branch `9e4dcf5`; `src/dictate/pro/client.py`, `src/dictate/pro/server.py`, `docs/goal.md` | Dictate implementation lane | Migration input | Keep local-first behavior and current `/v1` runtime unchanged while the client contract is migrated. |
| Arc Forge account, entitlement, and commerce models | `/home/samuel/repos/arc-forge-deck` `agent/deployment-harmony-phase2` @ `2ee29c9`; `arc_forge_console/models.py:100` (`PortalAccount`), `:363` (`Entitlement`), `:409` (`CommerceSubscription`) | External active `arc-forge-deck` owner | Production authority | Shared identity and commerce authority candidate; owner confirmation is required before Dictate treats the v1 contract as deployed. |
| Desktop auth router and application wiring | `/home/samuel/repos/arc-forge-deck` @ `2ee29c9`; `arc_forge_console/dashboard.py:12807` (`build_account_auth_router`), `arc_forge_console/main.py:312` (router inclusion) | External active `arc-forge-deck` owner | Production authority | Shared route implementation to reconcile with canonical HTTPS discovery, PKCE, device flow, and return-to-product behavior. |
| Process-memory auth/grant stores | `/home/samuel/repos/arc-forge-deck` @ `2ee29c9`; `arc_forge_console/dashboard.py:212` (`_dictate_auth_codes`), `:230` (`_dictate_device_codes`), `:236` (`_dictate_device_codes_by_user_code`), `:257` (`_refresh_tokens`), token logic around `:12111-12268` and `:12807+` | External backend owner | Migration input | Current implementation evidence, not a durable Phase 1 production authority. Do not duplicate it in Dictate. |
| Shared LiteLLM tooling | `/home/samuel/repos/arc-forge-deck` `litellm_gateway.py` and `config.py` `LITELLM_*` configuration | External backend owner for existing Deck policy/admin probe | Migration input | Shared tooling exists, but no proven Dictate audio contract; Dictate must not treat it as an approved STT authority without the handoff decision. |
| Live desktop discovery probes | Provided 2026-07-11 evidence: `https://console.arcforge.au/api/account/auth/desktop` and `https://deck.arcforge.au/api/account/auth/desktop` return `200`, advertise `http://` endpoints, and both public roots resolve to `/deck/login` with title `Deck` | External deployed service owner | Compatibility path / migration input | Evidence of current behavior only. It fails the future HTTPS and neutral Arc Forge return/branding gate; it is not evidence that the contract is deployed. |
| Dictate client production defaults | `src/dictate/pro/client.py` currently defaults to `console.arcforge.au` and uses `/v1` paths | Dictate client lane, pending shared owner route agreement | Compatibility path | Preserve for this round; migrate only after canonical origin, route paths, and owner handoff are confirmed. |
| In-repo Pro server | `src/dictate/pro/server.py` `/v1` | Dictate repository | Test/reference harness | Label and retain for local/reference tests; never describe it as the production account, commerce, gateway, or hosted-job authority. |
| Forge LLM gateway repository | `/home/samuel/repos/forge-llm-gateway`; supplied evidence says it is `311` commits behind `origin` | None for this work | Dead/excluded | Do not revive or use it as a second production gateway authority. |
| Dictate-side v1 contract | `docs/contracts/dictate-platform-v1.json` in this branch | Dictate-side planning artifact; shared owner confirmation pending | Migration input | Defines the proposed future boundary and compatibility label; it is not a deployed implementation claim. |
| Phase 0 handoff | `docs/platform/arc-forge-backend-handoff-v1.md` in this branch | Dictate lane → external `arc-forge-deck` owner | Migration input | Records the smallest requested shared changes and the pending confirmation gate. |

## Live evidence notes

The live observations above are recorded as supplied evidence for 2026-07-11;
this round does not mutate or authenticate to any live system. No credentials,
tokens, provider keys, audio, transcript, or user data are included here.

The `200` responses are not treated as proof of production correctness. The
advertised insecure URLs and Deck-branded `/deck/login` landing behavior remain
open migration findings for the shared owner.

## Phase 0 gate status

**PENDING — not passed.** The inventory identifies one external shared backend
owner and the current authorities, but owner confirmation, canonical route
agreement, HTTPS discovery correction, durable auth disposition, shared gateway
ownership, and contract acceptance remain outstanding.
