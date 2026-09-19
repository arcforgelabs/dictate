# Local-only strip: audit

Status: proposal. Nothing in this document has been deleted yet.

Dictate is no longer a commercial product. It is a local-first dictation app
worked on when there is time. Everything that exists to support accounts,
subscriptions, hosted transcription, cloud sync and cloud deployment is dead
weight and comes out.

The goal after the strip: **a nice working package for local dictation**, so a
user installs one thing and it works, instead of assembling a UI and a model
runtime themselves. No account. No API key. No network dependency in the
transcription path.

## Headline

Removing the cloud surface deletes roughly **20,300 lines across 51 files**,
about **37%** of `src` + `tests` combined (55,257 lines today). A further
~10,500 lines across 12 files need editing rather than deleting.

This is not only "delete the cloud code". A large part of the win is that
machinery which exists *because* the cloud can fail also stops being needed.

## Tier 1 — delete wholesale

These have no local-only purpose. Nothing survives them.

| Area | Files | LOC |
| --- | ---: | ---: |
| `src/dictate/pro/` — accounts, Stripe, hosted server, relay, signing, email | 15 | 6,793 |
| `src/dictate/api_keys.py`, `api_keys_dialog.py` | 2 | 1,346 |
| `src/dictate/sync.py`, `sync_engine.py` | 2 | 942 |
| `src/dictate/stt/{openai,gemini,xai}_backend.py` | 3 | 818 |
| `src/dictate/provider_supervisor.py` | 1 | 387 |
| Tests covering all of the above | 24 | 9,128 |
| `scripts/` — cloud sync audits/smokes, msstore submit | 4 | 913 |
| **Total** | **51** | **20,327** |

### Why `provider_supervisor.py` goes

Its own docstring says it "handles graceful degradation when the remote fails,
and schedules automatic recovery probes using class-aware exponential backoff",
with on-device as "the always-available floor". With no remote, there is no
degradation to manage and no probe to schedule — the floor becomes the whole
building. 387 lines of supervisor plus 1,188 lines of tests exist purely to
survive a network that local-only never touches.

This is the shape of the whole change: the cloud did not just add features, it
added failure modes, and the code handling those failure modes is larger than
the features were.

### `src/dictate/pro/` detail

`store.py` alone is 80 KB. With `client.py` (51 KB), `service.py` (36 KB) and
`server.py` (31 KB), four files carry most of the weight. `stripe_handler.py`,
`plans.py`, `browser_auth.py`, `email_delivery.py` and `signing.py` are
subscription and identity plumbing with no local equivalent.

Note `dictate-pro-server` is a console entry point in `pyproject.toml` — a
hosted server shipped inside a desktop app. That goes with the package.

## Tier 2 — edit, do not delete

These are load-bearing for local operation but currently reference cloud paths.

| File | LOC | What to remove |
| --- | ---: | --- |
| `src/dictate/ui_server.py` | 2,182 | `ProClient`, `ProviderSupervisor`, `PRODUCT_DESTINATIONS`, sync endpoints, all API-key endpoints |
| `src/dictate/daemon.py` | 1,938 | `ProviderSupervisor` wiring |
| `src/dictate/__main__.py` | 1,573 | `ProClientError`, supervisor, sync settings, API-key CLI commands |
| `src/dictate/tray.py` | 1,351 | API-key menu items and dialog launch |
| `src/dictate/stt/factory.py` | 742 | Cloud backend registration; `resolve_default_local_backend` already exists and becomes the only path |
| `src/dictate/windows_control.py` | 687 | API-key panel |
| `src/dictate/note_store.py` | 509 | `SyncOutbox` |
| `src/dictate/ui_launcher.py` | 400 | `ProviderSupervisor` |
| `src/dictate/config.py` | 390 | Sync record-category settings; `xai` hotword branch |
| `src/dictate/history.py` | 230 | `SyncOutbox` |
| `src/dictate/stt/__init__.py` | 87 | Cloud backend exports |

`ui/src/App.jsx` is the front-end equivalent — 185 lines match account / sync /
billing / API-key identifiers, and `ui/src/ipc.js` has 51. `productDestinations.js`
goes entirely.

## Tier 3 — docs to retire

Move to `docs/archive/` rather than delete, so the history stays readable:

- `DICTATE_PRO_CLOUD_SYNC_PLAN.md`
- `dictate-pro-subscription-architecture.md`
- `desktop-browser-signin-architecture.md`
- `dictate-pro-terms.md`
- `msstore-in-app-subscriptions.md`
- `deck-sections-and-dictate-space-spec.md`
- `platform/dictate-platform-inventory-v1.md`
- `platform/arc-forge-backend-handoff-v1.md`
- `contracts/dictate-platform-v1.json` (2,048 lines)

`dictate-privacy-policy.md` needs a rewrite, not an archive: with no account and
no network transcription path, the policy becomes short and much stronger.

## What stays

The local transcription path is already first-class, which is why this strip is
feasible rather than a rebuild:

- `stt/parakeet_backend.py`, `parakeet_pyannote_backend.py`,
  `parakeet_speaker_backend.py` — local Parakeet and diarisation
- `stt/faster_whisper_backend.py`, `whisper_cpp_backend.py`, `whisperx_backend.py`
- Audio capture, hotkey, tray, history, lexicon, note chunking, outputs
- Installers, updater, packaging
- `resolve_default_local_backend` / `resolve_default_local_model` in
  `stt/factory.py` — the local default already exists

Runtime dependencies in `pyproject.toml` need no change: they are already
local-ML (`faster-whisper`, `onnx-asr`, `onnxruntime`, `numpy`). There is no
Stripe or web-framework dependency to drop, because the hosted server was built
on the standard library. `cryptography` should be re-checked once sync is gone —
it may only be there for sync record encryption.

## Open questions

1. **Microsoft Store.** `msstore-*` workflows and docs assume a Store listing
   with in-app subscriptions. If distribution becomes GitHub Releases only,
   three workflows and two docs go too. Not assumed here.
2. **`history`/`note_store` outbox.** Both take `SyncOutbox`. Confirm removing
   it leaves local history intact — it should, but the write path needs reading
   before cutting.
3. **Config migration.** Existing users have `stt_backend: openai|gemini|xai` in
   their config. The strip needs a migration that falls back to the local
   default instead of failing at startup.
4. **Stored secrets.** Removing `api_keys.py` should also clear previously saved
   keys from the OS secret store, rather than orphaning them.

## Suggested sequence

Each step should land green on its own.

1. Delete `pro/` and its tests; drop the `dictate-pro-server` entry point.
2. Delete cloud STT backends; collapse `factory.py` onto the local default.
3. Delete `provider_supervisor.py`; unwire from daemon, ui_server, ui_launcher,
   `__main__`.
4. Delete sync; unwire `SyncOutbox` from `history.py` and `note_store.py`.
5. Delete API-key management; strip the tray, control panel and UI surfaces.
6. Add the config migration for orphaned cloud backend selections.
7. Archive docs; rewrite the privacy policy.
