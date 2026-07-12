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

Wave 0 is marked **PASSED — planning authority lock only**. This does not claim
that any shared backend or live deployment conforms. Unknown deployment facts
remain Wave 1–4 verification tasks and do not block independent implementation.

Primary artifacts:

- [Platform contract](contracts/dictate-platform-v1.json)
- [Platform inventory](platform/dictate-platform-inventory-v1.md)
- [Backend handoff](platform/arc-forge-backend-handoff-v1.md)
- [Contract tests](../tests/test_dictate_platform_contract.py)

## Current blocker: two verified P1 findings

The final read-only Sol verification of `96b974c..77b1c47` returned **NOT
CLEAN** with exactly two P1 findings. All other reviewed findings were verified
fixed.

### P1 — key-envelope response signature shape

`docs/contracts/dictate-platform-v1.json` defines
`KeyEnvelopeRecord.server_signature` as `string | null`, but the current
reference service returns a signature bundle object.

Evidence:

- `docs/contracts/dictate-platform-v1.json` around `KeyEnvelopeRecord`
- `src/dictate/pro/service.py` around line 805
- `src/dictate/pro/store.py` around lines 2030–2041
- `src/dictate/pro/signing.py` around lines 71–77
- Existing contract tests validate the write request but not current-shaped
  save/list response records.

Required outcome:

1. Add an explicit signature-bundle schema matching
   `{algorithm, key_id, public_key, signature}`.
2. Reference that object (or `null`, only if the intended canonical response
   genuinely permits unsigned legacy records) from `KeyEnvelopeRecord`.
3. Add executable current-shaped `KeyEnvelopeRecord` and `KeyEnvelopeList`
   fixtures/tests for save/list responses.
4. Keep the future canonical contract distinct from any deliberately labelled
   legacy behavior.

### P1 — usage idempotency and exactly-once lifecycle conflict

The contract says correlated reservation/settlement/rollback events share an
idempotency key, while `_UsageLedgerModel` indexes only by
`(account_id, idempotency_key)`. A terminal event with the shared key is thus
rejected as a duplicate. The existing fixture hides this by assigning different
keys. The model also accepts a second settlement for the same reservation.

Evidence:

- `docs/contracts/dictate-platform-v1.json` around `UsageEvent` invariants,
  `usage_events.cross_event_invariants`, and `requirements.gateway_usage`
- `tests/test_dictate_platform_contract.py` around `_UsageLedgerModel` and the
  executable usage lifecycle test

Required outcome:

1. Choose and encode one unambiguous idempotency model. A safe direction is a
   gateway request/correlation key shared across the lifecycle plus a distinct
   event idempotency key scoped by lifecycle/event type, but the contract and
   fixtures must agree.
2. Enforce linked account/request/job/period/correlation/predecessor fields.
3. Enforce at most one effective settlement per reservation.
4. Make duplicate gateway retries replay the original reservation/outcome.
5. Reject over-settlement and ensure exactly one effective rollback.
6. Add executable positive and negative tests using the same correlation model
   the contract specifies.

Do not begin Wave 1 until these two P1s are fixed and the final review is clean,
unless the user explicitly waives the Wave 0 review gate.

## Recommended next Forge actions

1. Read the full Forge skill at `/home/samuel/.agents/skills/forge/SKILL.md` and
   the complete current `docs/goal.md`.
2. Confirm the worktree is clean and HEAD is this handover commit.
3. Resume the same Luna builder if the headless session remains available:
   `019f512c-7b34-7ff1-b4e5-82d598645649`. Otherwise start a new Luna builder
   and explicitly state that this is a handover after the previous session.
4. Give Luna only the two accepted P1 outcomes above; no new archaeology and no
   external-repository edits.
5. Independently rerun the focused gates below.
6. Run one fresh, read-only `gpt-5.6-sol` verification against only the fix diff
   and these two findings.
7. If clean, start Wave 1 as one coherent backend milestone under the shortened
   execution model. Wave 1 affects the shared backend, so first coordinate the
   external repository owner rather than editing their dirty branch silently.

The final Sol review output from the previous run is stored at
`/tmp/forge-wave0-extended-final-review.txt` if that temporary file survives.

## Last independently verified gates

At `77b1c47`, the conductor independently ran:

```text
python3 -m compileall -q src tests scripts                          PASS
cached Ruff 0.15.21 on tests/test_dictate_platform_contract.py    PASS
focused Python tests                                               71 passed
UI Vitest suite                                                    98 passed (6 files)
UI production build                                                PASS (23 modules)
python3 -m json.tool contract                                      PASS
git diff --check                                                   PASS
```

Useful focused commands:

```bash
python3 -m compileall -q src tests scripts
/home/samuel/.cache/uv/archive-v0/A-b7jvP_Q2_JHBjciDrf3/bin/ruff check tests/test_dictate_platform_contract.py
.venv/bin/pytest -q tests/test_dictate_platform_contract.py tests/test_pro_client.py tests/test_transcription_plan_audit.py tests/test_sync.py
npm --prefix ui test -- --run
npm --prefix ui run build
python3 -m json.tool docs/contracts/dictate-platform-v1.json >/dev/null
git diff --check
```

The literal `uv run --with ruff` path intermittently failed because the network
was unavailable and uv could not reuse its read-only cache. The cached Ruff
binary above is already present and was independently verified.

## External repository boundary

The shared backend evidence is pinned read-only to:

```text
/home/samuel/repos/arc-forge-deck
revision 2ee29c9dbefb5208aea331042f56b8fad7112b4f
branch observed: agent/deployment-harmony-phase2
```

That repository had unrelated uncommitted work owned by another active lane.
Use `git show 2ee29c9:<path>` for evidence. Do not modify, stage, commit, stash,
or clean its working tree without explicit coordination and authority.

Observed live discovery endpoints returned HTTP-advertised URLs and Deck-branded
login behavior, but the deployed revision was unknown. Treat those facts as
migration/verification inputs, not proof that the pinned source is deployed.

Nothing on this Dictate branch has been pushed, merged, deployed, or released.
