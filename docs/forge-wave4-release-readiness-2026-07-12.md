# Forge Wave 4 — Release readiness evidence

**Date:** 2026-07-12 (Australia/Adelaide)  
**Status:** MERGED + PRODUCTION DEPLOYED — canary / migration counts / production soak for durable browser auth still open (local cutover complete)

**Dictate branch:** `master` (merged PR [#17](https://github.com/arcforgelabs/dictate/pull/17) @ `f6ea882`)  
**Verify tip:** `git -C /home/samuel/repos/dictate rev-parse --short HEAD`

**Shared backend:** arc-forge-deck `main` — Dictate Pro platform PR [#208](https://github.com/arcforgelabs/arc-forge-deck/pull/208) merge `f5e6be3`; production currently @ `7ee9c07` (includes follow-on #209). Forge feature branches deleted after merge.

**Deployment Harmony (closed):** merged to arc-forge-deck `main` @ `7db8c38` (PR 207).

**Production image:** `ghcr.io/arcforgelabs/arc-forge-console:sha-7ee9c07d4a798b0fe660b36f41133f8a0f806540`  
**Deploy run:** https://github.com/arcforgelabs/arc-forge-deck/actions/runs/29193423615  
**Live discovery (2026-07-12):** `https://console.arcforge.au/api/account/auth/desktop` returns HTTPS authorize/token/device-code endpoints; `https://console.arcforge.au/healthz` → 200.

## Executive summary

Waves 0–3 are implemented and merged. Wave 4 local proof shipped; push/merge/deploy
of the Dictate Pro platform stack is done. Remaining true-DoD gaps: internal canary
(hosted + sync + revoke), migration reconciliation counts, and production soak for
durable browser auth (AccountChallengeStore + PortalRefreshStore; local cutover on
`forge/dictate-pro-dod-closeout`).

**E2E scoreboard of record:** [goal.md](goal.md) (progress table + DoD). This
readiness doc is release evidence; [forge-handover-2026-07-12.md](forge-handover-2026-07-12.md)
is session continuity.

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

## What is UNKNOWN (requires further gate)

| Item | Why unknown | Action needed |
| --- | --- | --- |
| Canary metrics | No production-shaped soak yet | Internal canary with opt-in cohort |
| Rolling deploy durability | Local SQLite tests ≠ multi-instance Postgres + Redis | Staging/prod-shaped soak under load |
| Object-store + worker split | Hosted worker runs in-request in tests | Production worker topology |
| Migration counts | No production account/subscription reconciliation run | Migration dry-run with counts |
| Durable browser auth production soak | Local cutover to AccountChallengeStore + PortalRefreshStore; multi-instance/restart proof pending | Staging soak + canary |

## Residual risks (accepted for local gate; not for production without plan)

1. **Device-key wrapping deferred** — hosted results use server-managed AES-256-GCM
   (account/device/job AAD), not device-public-key wrapped ciphertext.
2. **Recovery approve disabled (`501`)** — cryptographic recovery verification not
   implemented; endpoint fail-closed.
3. **Durable browser auth (local)** — magic links, resets, login codes, browser MFA,
   companion OAuth, and `portal_refresh` now use hashed SQLite authorities via
   `portal_account_auth` adapters; production rolling-deploy/restart soak still required.
4. **Sync export/delete** — Wave 3 deferred; not in local proof scope.
5. **Unregistered hosted `device_id` spoof** — unbound bearer may still create jobs
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

- [x] Review this document + `docs/forge-handover-2026-07-12.md`
- [x] Authorize push of `forge/wave1-durable-auth` and `forge/dictate-pro-platform`
- [x] Record deployed SHA and run discovery/HTTPS verification
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
<!-- w4r3-sync: 15091 -->
