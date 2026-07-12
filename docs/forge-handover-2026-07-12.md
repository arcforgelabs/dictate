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
(commit `2ca2b8c`; not pushed).

Implemented in the shared backend:

1. **Single commerce authority** — `dictate_entitlement_for` and
   `_require_active_dictate_subscription` read `CommerceSubscription` +
   `Entitlement` only. Legacy `DictateSubscription` rows are one-way bridged on
   first read via `_bridge_legacy_dictate_subscription_to_commerce` (Stripe
   webhooks still ingest legacy rows; they are not a competing gate authority).
2. **Usage ledger lifecycle** — new `DictateUsageLedger` module with
   reservation → settlement|rollback|rejection, gateway correlation fields
   (`request_id`, `idempotency_key`, `correlation_id`), and event_type-scoped
   retry dedup per `usage_events.idempotency_model` in
   `docs/contracts/dictate-platform-v1.json`. `DictateUsageEvent` model and DB
   migration extended; job create reserves, reconcile settles, failure paths
   rollback.
3. **Executable tests** — `tests/test_dictate_usage_ledger.py` (reserve→settle
   idempotent retry, over-settlement rejected, terminal exclusivity,
   duplicate-key rejection); entitlement bridge test in same file.

Remaining Wave 1 work (not in Slice 2): hosted jobs hardening (Wave 2 overlap),
sync/devices UX (Wave 3), portal browser `portal_refresh` cookie durability.

## Recommended next Forge actions

1. Read the full Forge skill at `/home/samuel/.agents/skills/forge/SKILL.md` and
   the complete current `docs/goal.md`.
2. Confirm both worktrees are clean and note the new commit SHAs below.
3. Run focused gates on `arc-forge-deck` and `dictate` (commands below).
4. Run one fresh, read-only Sol review against the Wave 1 Slice 2 diff.
5. Continue Wave 1 Slice 3+ only after the slice review is clean or explicitly
   waived.

## Last independently verified gates

At `2ca2b8c` on `arc-forge-deck` (Slice 2) and `d552dce` on `dictate`, the
conductor independently ran:

```text
arc-forge-deck:
  uv run python -m pytest tests/ -k "entitle or commerce or usage or dictate_subscription or durable_auth" -q   PASS
  uv run python -m pytest tests/test_dictate_desktop_auth.py tests/test_durable_auth.py -q                        PASS
  git diff --check                                                                                                PASS

dictate:
  python3 -m compileall -q src tests scripts                                                                    PASS
  .venv/bin/pytest -q tests/test_dictate_platform_contract.py tests/test_pro_client.py                            PASS
  git diff --check                                                                                                PASS
```

Useful focused commands:

```bash
# arc-forge-deck
uv run python -m pytest tests/ -k "entitle or commerce or usage or dictate_subscription or durable_auth" -q
uv run python -m pytest tests/test_dictate_desktop_auth.py tests/test_durable_auth.py -q
git diff --check

# dictate
python3 -m compileall -q src tests scripts
.venv/bin/pytest -q tests/test_dictate_platform_contract.py tests/test_pro_client.py
git diff --check
```

## External repository boundary

The shared backend implementation for Wave 1 lives on:

```text
/home/samuel/repos/arc-forge-deck
branch: forge/wave1-durable-auth
parent: forge/handover-sharpen @ ae663a0
commits:
  Slice 1 durable auth: 2a19ec4
  Slice 2 commerce + usage ledger: 2ca2b8c
```

Do not push, merge, or deploy without explicit human go.

Nothing on this Dictate branch has been pushed, merged, deployed, or released.
