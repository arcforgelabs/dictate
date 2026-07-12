# Forge Wave 4 — Release readiness evidence (local)

**Date:** 2026-07-12 (Australia/Adelaide)  
**Status:** LOCAL PROOF ONLY — **not deployed**, **not pushed**, **not released**  
**Dictate branch:** `forge/dictate-pro-platform` @ see handover for tip SHA  
**Shared backend branch:** `forge/wave1-durable-auth` @ `67914b9` (Wave 4 R1 tip)

## Executive summary

Waves 0–3 are implemented and conductor-green on local forge branches. Wave 4
Round 1 integrates documentation, quarantines residual interim auth claims, runs
broad focused test suites, and records what is proven locally versus what remains
**UNKNOWN** until an explicit human authorizes push, canary, and production deploy.

Nothing in this document authorizes push, merge, Helm changes, live canary, or
credential rotation.

## What is proven locally

| Area | Evidence | Forge commits (local) |
| --- | --- | --- |
| Wave 0 contract lock | `docs/contracts/dictate-platform-v1.json`, contract tests | `d552dce` … `77b1c47` |
| Durable desktop auth | `DurableAuthStore` for auth codes, device codes, refresh families; replay tests | `2a19ec4`, `779daf9` |
| Single commerce authority | `CommerceSubscription` + `Entitlement` gates; one-way legacy bridge only | `2ca2b8c`, `28caac1` |
| Usage ledger lifecycle | reserve/settle/rollback, terminal exclusivity, idempotent retry | `2ca2b8c`, `6896fc4` |
| Governed hosted jobs | durable lifecycle, server-managed encrypted artifacts, audio cleanup | `6896fc4`, `d069430` |
| Devices + encrypted sync | unified revoke, sync envelope path, device-bound access JWT | `cbbda15`, `779daf9` |
| Desktop convergence | `platform_state.py`, selective session clearing, UI sync state | `d23adc3`, `b102c33` |
| Residual auth quarantine | `residual_interim_auth.py` labels non-durable stores | Wave 4 R1 |

## What is UNKNOWN (requires human gate)

| Item | Why unknown | Human action needed |
| --- | --- | --- |
| Deployed SHA | Forge branches are local-only; no live revision proof | Push + deploy + record SHA |
| Canary metrics | No production-shaped soak | Internal canary with opt-in cohort |
| Rolling deploy durability | Local SQLite tests ≠ multi-instance Postgres + Redis | Staging/prod-shaped integration |
| Object-store + worker split | Hosted worker runs in-request in tests | Production worker topology |
| Live discovery HTTPS | Historical probes showed HTTP `issuer` URLs | Post-deploy discovery verification |
| Migration counts | No production account/subscription reconciliation run | Migration dry-run with counts |
| Email login-code durability | `_login_codes` remains residual interim | Migrate or accept risk |
| Browser `portal_refresh` | In-memory cookie refresh, not DB-backed | Durable browser refresh or document limit |

## Residual risks (accepted for local gate; not for production without plan)

1. **Device-key wrapping deferred** — hosted results use server-managed AES-256-GCM
   (account/device/job AAD), not device-public-key wrapped ciphertext.
2. **Recovery approve disabled (`501`)** — cryptographic recovery verification not
   implemented; endpoint fail-closed.
3. **`portal_refresh` in-memory** — browser portal refresh cookies may not survive
   restart/rolling deploy (labelled RESIDUAL_INTERIM).
4. **Email login-code in-memory** — `/api/account/auth/login-code` uses
   `_login_codes` dict; not DurableAuthStore (labelled RESIDUAL_INTERIM).
5. **Legacy companion `_auth_codes`** — companion enrollment only; not Dictate
   desktop PKCE (labelled RESIDUAL_INTERIM).
6. **Sync export/delete** — Wave 3 deferred; not in local proof scope.
7. **Unregistered hosted `device_id` spoof** — unbound bearer may still create jobs
   for unregistered device_id strings (registered devices require bound JWT).

## Rollback notes (pre-deploy planning)

- **Gateway/provider disable:** Desktop `platform_state` keeps local execution;
  signed-in state survives transient outages; session clears only on auth revoke/expiry.
- **Hosted lane off:** Local STT backends remain default; `get_state()` reports
  `execution: local` when provider mode is private.
- **Commerce rollback:** Entitlement gates read `CommerceSubscription` only;
  legacy `DictateSubscription` rows remain ingest-only via Stripe webhooks.
- **Auth rollback:** DurableAuthStore tables are additive SQLite migrations;
  rollback = redeploy prior image + retain DB (refresh families may need manual revoke).
- **Deploy rollback:** Standard container image rollback; no Helm changes in this wave.

## Recommended human gate checklist

- [ ] Review this document + `docs/forge-handover-2026-07-12.md`
- [ ] Authorize push of `forge/wave1-durable-auth` and `forge/dictate-pro-platform`
- [ ] Record deployed SHA and run discovery/HTTPS verification
- [ ] Run migration dry-run with explicit reconciliation counts
- [ ] Schedule internal canary (hosted + sync + revoke) before stable promotion
- [ ] Confirm privacy/support pages published (`docs/dictate-privacy-policy.md`)

## Broad gate commands (Wave 4 Round 1)

```bash
# arc-forge-deck — auth, commerce, hosted, devices/sync
cd /home/samuel/repos/arc-forge-deck
uv run python -m pytest \
  tests/test_dictate_devices_sync.py \
  tests/test_dictate_hosted_jobs.py \
  tests/test_dictate_usage_ledger.py \
  tests/test_durable_auth.py \
  tests/test_dictate.py \
  tests/test_dictate_desktop_auth.py \
  tests/test_dictate_account_return.py \
  tests/test_commerce.py \
  -q
git diff --check

# dictate — contract, client, platform state, auth, sync, UI backend
cd /home/samuel/repos/dictate
.venv/bin/pytest -q \
  tests/test_dictate_platform_contract.py \
  tests/test_pro_client.py \
  tests/test_platform_state.py \
  tests/test_pro_auth.py \
  tests/test_pro_service.py \
  tests/test_ui_server.py \
  tests/test_sync.py \
  tests/test_sync_engine.py \
  tests/test_browser_auth.py
git diff --check

# ui vitest (optional quick gate)
cd ui && npm test
```

Record actual pass counts in the handover after each run.

**Wave 4 Round 1 results:** deck 124 passed; dictate 221 passed; ui vitest 98 passed.
