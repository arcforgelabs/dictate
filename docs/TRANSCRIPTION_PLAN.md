# Dictate Transcription Plan

Date: 2026-07-05

**Status:** Active scoped authority for local transcription and release evidence.

This is the authoritative planning document only for Dictate local
transcription, recordings, meetings, model lanes, timestamping, speaker
attribution, GPU support, and their release evidence. `VISION.md` is the
current cross-system authority; this plan is subordinate for account, cloud,
commerce, and Deck decisions. Older research/cost notes are archived under
`docs/archive/`.

## Goal

Ship a clean local-first transcription stack where:

1. Push-to-talk dictation and plain recordings use the same verbatim ASR path.
2. Meeting mode always produces a speaker-attributed transcript.
3. Parakeet is the local ASR foundation across CPU, NVIDIA GPU, and AMD GPU
   lanes.
4. Whisper/faster-whisper are treated as temporary migration scaffolding and are
   removed from product lanes once Parakeet coverage is complete.
5. AMD GPU support is first-class, not a fallback footnote.

## Deployable Goal

Set this document as the active scoped deployment goal for local transcription
and release evidence:

> Implement `docs/TRANSCRIPTION_PLAN.md` end to end so Dictate is ready for
> human testing on machines with the capabilities named here, including local
> CPU, NVIDIA CUDA, AMD GPU readiness, meeting speaker attribution, and a
> Windows build verified in the local VM lab.

This document is the source of truth only for the scoped transcription/model
deployment. Older goal, model-research, and cost-planning notes are archived or
reduced to pointers. If another document conflicts with this plan on local
transcription or release evidence, update that document to point here. For
product direction, follow `VISION.md`.

## Planning Map

Use this file as the only active plan for transcription deployment. Other docs
have narrower roles:

| File | Role |
| --- | --- |
| `../VISION.md` | Product direction: Dictate is local-only. |
| `docs/GOALS.md` | Compatibility pointer for older links. |
| `docs/archive/` | Historical notes only; not current direction. |
| `benchmarks/README.md` | Benchmark command and artifact format referenced by this plan. |
| `docs/desktop-packaging.md` | Packaging runbook; not a separate deployment plan. |

Do not create a second planning landing page for this work. If implementation
details outgrow this document, keep this plan as the goal and link to focused
runbooks or specs from the relevant acceptance gate.

## Deployment Snapshot

Current verified state:

1. Linux source/local install is usable for human testing on this workstation.
2. Fresh CPU English installs default to Parakeet v2 where the runtime is
   available.
3. Parakeet CUDA can load on Samuel's NVIDIA workstation and passes doctor,
   model-prepare, and silence-smoke checks.
4. The Windows `win11-dev` VM passes source install, update, uninstall, and
   desktop build smokes, including Store MSIX packaging.
5. The Windows human-test artifacts currently proven in the local VM are the
   no-bundle executable plus `dictate-engine.exe` sidecar and a Store-style
   `.msix` package. MSI/NSIS direct-download installers are still not promoted.
6. The engine has a strict speaker-attribution contract for meetings:
   `require_speaker_attribution=True` fails closed when the selected backend
   cannot produce speaker-attributed output. Daemon, loopback API, and desktop
   UI meeting start/stop paths are wired.

Deployment blockers before calling this plan complete:

1. Promote Parakeet CUDA from synthetic benchmark evidence to curated human
   speech benchmark evidence suitable for a product lane.
2. Validate AMD GPU execution on representative Linux ROCm/MIGraphX and Windows
   DirectML or AMD-capable ONNX Runtime machines.
3. Benchmark and promote at least one local speaker-attribution lane for
   Meeting mode.
4. Prototype and benchmark DiariZen, NVIDIA Streaming Sortformer v2.1, and the
   initial Parakeet+pyannote Community-1 backend against the same meeting
   fixtures.
5. Ship integrated timestamp/segment/speaker metadata instead of string-only
   transcripts all the way through the meeting UI/export workflow. The backend,
   engine, daemon, note-store, live expanded-note UI, and Markdown export
   foundation now exists, and persisted notes rehydrate with speaker/timestamp
   segments after restart. Notes search and list-level Markdown export are
   segment-aware. Timestamp quality validation remains.
6. Decide the public Windows promotion path: current VM evidence proves the
   no-bundle executable and MSIX packaging paths; MSI/NSIS direct-download
   bundling is still not promoted.
7. Staged update preparation is deferred out of the human-test release. The
   human-test release uses the tested immediate source update path plus the
   documented MSIX/manual package path.

## Product Rules

| User Action | Internal Behavior |
| --- | --- |
| Push-to-talk dictation | Verbatim ASR, no speaker attribution. |
| Plain recording | Same ASR behavior as push-to-talk, no speaker attribution. |
| Meeting | ASR plus speaker attribution. No exceptions. |

The UI should expose product language such as `Meeting` and `Record`. It should
not expose primary controls named `diarization`, `ASR backend`, `CUDA`, `MIGraphX`,
or similar engine terms.

## Local ASR Lanes

| Lane | Target | Status | Decision |
| --- | --- | --- | --- |
| English CPU | Parakeet v2, `nvidia/parakeet-tdt-0.6b-v2` | Wired today through ONNX/onnx-asr CPU path | Default English local lane. |
| English NVIDIA GPU | Parakeet v2 through CUDA-capable runtime | Fresh default when Parakeet is available; wired for smoke, not benchmark-promoted | Same English model, GPU runtime for speed. |
| Multilingual NVIDIA GPU | Parakeet v3, `nvidia/parakeet-tdt-0.6b-v3` | Wired for model selection, not benchmark-promoted | Strategic multilingual local lane. |
| Multilingual CPU | Parakeet v3 | Feasibility benchmark | Use only if CPU latency is acceptable. |
| English AMD GPU | Parakeet v2 through AMD runtime | Fresh default when Parakeet is available; explicit provider readiness wired | First-class AMD lane. |
| Multilingual AMD GPU | Parakeet v3 through AMD runtime | Model wired, representative AMD validation still required | First-class AMD lane. |

Current `faster-whisper/large-v3` support is a bridge for this workstation, not
the product direction.

## Implementation Status

As of 2026-07-05, Dictate accepts `amd` as an explicit compute-device lane in
the CLI/runtime profile surface and doctor/preflight can verify whether ONNX
Runtime exposes an AMD-capable execution provider. Parakeet v2 and v3 are wired
through the ONNX/onnx-asr loader, and explicit CUDA/AMD Parakeet requests pass
provider lists into ONNX Runtime instead of silently running the CPU path.

Fresh local backend selection is now Parakeet-first across CPU, CUDA, and AMD
when the Parakeet runtime is importable. This is still not a performance-promoted
GPU lane: representative NVIDIA/AMD hardware benchmarks, package/provider
coverage, and failure-mode testing remain before claiming CUDA or AMD speed
targets.

NVIDIA CUDA evidence on Samuel's workstation (recorded on the CUDA 12 lane,
`onnxruntime-gpu` 1.23.2; the pin moved to 1.30 / CUDA 13 on 2026-09-20 and
this list must be re-run before the GPU lane is called re-validated):

1. `onnxruntime-gpu==1.23.2` exposes `CUDAExecutionProvider` after
   `onnxruntime.preload_dlls()` loads the CUDA/cuDNN libraries from the venv.
2. `dictate doctor --stt-backend parakeet --device cpu --quick` is healthy.
3. `dictate doctor --stt-backend parakeet --device cuda --quick` is healthy.
4. `dictate doctor --stt-backend parakeet-pyannote --device cuda --quick`
   imports the Meeting runtime and detects CUDA, but exits with code `2` until
   pyannote Community-1 access is configured through accepted Hugging Face model
   terms plus token or an offline local model path.
5. `torch==2.8.0+cu128` reports CUDA available on `NVIDIA GeForce RTX 4090`,
   and `pyannote.audio==4.0.5` imports successfully.
6. `dictate prepare-model --stt-backend parakeet --model parakeet-tdt-0.6b-v2
   --device cuda --compute-type int8` loads successfully.
7. `dictate prepare-model --stt-backend parakeet --model parakeet-tdt-0.6b-v3
   --device cuda --compute-type int8` loads successfully.
8. `dictate prepare-model --stt-backend parakeet-pyannote --model
   parakeet-tdt-0.6b-v2 --device cuda --compute-type int8` now validates both
   the Parakeet ASR resource and the pyannote speaker-attribution resource. On
   this workstation it loads Parakeet on CUDA, then exits with code `2` because
   pyannote Community-1 model access is not configured.
9. Parakeet v2 and v3 CUDA smoke transcriptions on one second of silence return
   `no_speech` with an empty transcript, as expected.
10. The Parakeet backend exposes a plain ASR `transcribe_segments(...)` path via
   `onnx-asr` timestamp adapters when available. The engine and benchmark CLI
   consume this path for non-meeting recordings so Parakeet dictation can carry
   `TranscriptSegment` timing metadata, not just plain text.
11. A repeatable local flite-smoke benchmark fixture generator exists at
    `scripts/generate-benchmark-fixtures.sh`. These fixtures are for speed,
    JSON-shape, timestamp, and gate smoke evidence only; curated human speech
    recordings are still required for final WER promotion.
12. A repeatable longer flite benchmark fixture generator exists at
    `scripts/generate-long-benchmark-fixtures.sh`. It writes a longer WAV plus
    `manifest.csv` and `manifest-3x.csv` so CPU/CUDA comparisons can run
    against the same repeated synthetic audio with less startup-overhead
    distortion than the short smoke fixture.
13. A repeatable local flite meeting-smoke fixture generator exists at
    `scripts/generate-meeting-benchmark-fixtures.sh`. It produces a synthetic
    two-speaker WAV plus timestamped `segments_json` references for meeting
    benchmark JSON-shape, DER, speaker-confusion, and boundary-metric smoke
    validation.

Windows CUDA packaging status:

1. `install-windows.ps1` now detects NVIDIA hardware through `nvidia-smi`,
   `Win32_VideoController`, or PCI vendor `VEN_10DE`.
2. On detected NVIDIA hardware, or when called with `-ForceCuda`, the installer
   replaces the CPU-only `onnxruntime` wheel with
   `onnxruntime-gpu[cuda,cudnn]>=1.30,<1.31`. This follows ONNX Runtime's
   documented CUDA/cuDNN site-package preload path and avoids requiring a manual
   CUDA Toolkit install for the Parakeet ONNX CUDA lane. The 1.30 wheels bundle
   the CUDA 13 runtime, so the machine needs NVIDIA driver 580 or newer.
3. `-NoCuda` suppresses CUDA package installation for CI, constrained machines,
   and user support cases.
4. The hosted npm install/update wrappers pass `-ForceCuda` and `-NoCuda`
   through to the source installer/updater.
5. The `win11-dev` lab VM currently exposes only a `Red Hat QXL controller`.
   It verifies the non-NVIDIA Windows install path and startup/user-profile
   surface. With `-ForceCuda`, it also verifies that the GPU wheel installs,
   `onnxruntime.preload_dlls()` can load the bundled CUDA/cuDNN runtime DLLs,
   `CUDAExecutionProvider` appears, and `dictate doctor --device cuda` is
   healthy. It still cannot prove real NVIDIA inference until a GPU is passed
   through or a physical Windows NVIDIA test host is used.

Windows VM evidence on `win11-dev`:

1. `scripts/windows-vm-smoke.sh --vm win11-dev --mode syntax` passes.
2. `scripts/windows-vm-smoke.sh --vm win11-dev --mode install` passes,
   including clean guest app-data setup, install, Python compile, 314 focused
   Windows tests, `dictate --version`, default Parakeet doctor, and cleanup.
3. `scripts/windows-vm-smoke.sh --vm win11-dev --mode lifecycle` passes,
   including clean install, update, default Parakeet doctor, and uninstall.
4. `scripts/windows-vm-smoke.sh --vm win11-dev --mode build --keep-guest-workdir`
   passes for the no-bundle Windows desktop build. Verified guest artifacts:
   `C:\Users\Public\dictate-vm-smoke\source\ui-shell\src-tauri\target\release\dictate-ui-shell.exe`
   and
   `C:\Users\Public\dictate-vm-smoke\source\ui-shell\src-tauri\target\release\engine\dictate-engine.exe`.
5. Current dirty-tree no-bundle build verification after the preflighted lane
   runner, stricter plan audit, refreshed install smoke, validated AMD evidence
   import, and segment-aware UI refresh:
   `scripts/windows-vm-smoke.sh --vm win11-dev --mode build --timeout 1800
   --keep-guest-workdir` passed on 2026-07-05. The guest rebuilt the UI with
   Vite, froze and smoke-tested the Python engine sidecar, built the Tauri shell
   with `DICTATE_BUNDLES=no-bundle`, and verified the same no-bundle shell
   executable and engine sidecar artifact paths listed above.
6. Current dirty-tree MSIX verification after the preflighted lane runner,
   stricter plan audit, refreshed install smoke, validated AMD evidence import,
   segment-aware UI refresh, and refreshed no-bundle build:
   `scripts/windows-vm-smoke.sh --vm win11-dev --mode msix --timeout 2400
   --keep-guest-workdir` passed on 2026-07-05. The builder regenerated the UI
   with Vite, froze and smoke-tested the Python engine sidecar, built the Tauri
   shell, packed the MSIX with Windows SDK `makeappx.exe`, unpacked it, and
   validated manifest identity plus `dictate-ui-shell.exe`, logo assets, and
   `engine\dictate-engine.exe`. Verified
   guest artifact:
   `C:\Users\Public\dictate-vm-smoke\source\packaging\msix\out\ArcForgeDictate_2026.7.4.0_x64.msix`.
7. Current dirty-tree Windows install verification after the evidence collector,
   preflighted lane runner, stricter plan audit, Parakeet-first default,
   Meeting readiness, and model-preparation changes:
   `scripts/windows-vm-smoke.sh --vm win11-dev --mode install --timeout 1800
   --keep-guest-workdir` passed on 2026-07-05. The smoke resets the guest
   Dictate app-data directory, seeds a fresh config, compiles Python sources,
   runs 314 focused tests with 16 skips in the guest, verifies `dictate
   2026.7.4`, runs `dictate doctor --quick --type-backend pynput`, and reports
   `STT backend: parakeet` with `STT model: parakeet-tdt-0.6b-v2` before
   uninstalling cleanly. The guest selection now includes Meeting lane config
   and daemon behavior through `tests.test_config_commands`,
   `tests.test_config_selection`, and `tests.test_daemon_history`.
8. Windows AMD DirectML packaging smoke now passes: `scripts/windows-vm-smoke.sh
   --vm win11-dev --mode amd --timeout 1800 --keep-guest-workdir` passed on
   2026-07-05 after the preflighted lane runner, stricter plan audit, refreshed
   install smoke, and current package checks. This caught and fixed a marker bug
   where Windows reports `platform_machine == "AMD64"` rather than `x86_64`;
   the `amd` and `gpu` optional dependency markers now include both. The latest
   AMD smoke resets Dictate app data, seeds a fresh config, runs 196 focused
   tests with 15 skips, installs `onnxruntime-directml==1.23.0`, verifies
   `DmlExecutionProvider`, and `dictate doctor --stt-backend parakeet --device
   amd --quick --type-backend pynput` reports the Parakeet AMD DirectML lane
   healthy. This proves Windows DirectML package/readiness wiring, not real
   Radeon performance.
9. Current dirty-tree Windows lifecycle verification after the preflighted lane
   runner, stricter plan audit, refreshed install smoke, current package checks,
   and refreshed AMD DirectML smoke:
   `scripts/windows-vm-smoke.sh --vm win11-dev --mode lifecycle --timeout 2400
   --keep-guest-workdir` passed on 2026-07-05. It performed the clean install
   path with 196 focused tests and 15 skips, ran update, then ran default
   `dictate doctor --quick --type-backend pynput` again and reported the same
   Parakeet v2 default before uninstalling.

Windows MSI/NSIS installer bundling is not yet promoted. In the current `win11-dev` VM,
Tauri/WiX MSI bundling fails because `candle.exe` exits with `-2146232576`
(CLR/.NET runtime load failure), and NSIS bundling also fails inside Tauri. The
verified Windows human-test artifacts are currently the no-bundle executable
plus engine sidecar and the Store-style MSIX package, not MSI/NSIS installers.

Update scope decision: Staged update preparation is deferred out of the
human-test release. The human-test release uses the tested immediate source update path
(`update-windows.ps1` through `scripts/windows-vm-smoke.sh --mode lifecycle`)
plus the documented MSIX/manual package path. The source lifecycle
smoke verifies install, update, post-update doctor, and uninstall on `win11-dev`;
the staged `available -> preparing -> ready` UX and persistent skipped-version
state are deferred until after human testing.

Current AMD readiness behavior:

1. `dictate doctor --stt-backend parakeet --device amd --quick` requires an
   ONNX Runtime AMD-capable provider.
2. Accepted provider signals are `MIGraphXExecutionProvider`,
   `ROCMExecutionProvider`, or `DmlExecutionProvider`.
3. Windows AMD installs have an explicit `amd` optional dependency group that
   installs `onnxruntime-directml`, giving ONNX Runtime a DirectML provider path
   for Radeon customers on Windows.
4. Linux AMD remains ROCm/MIGraphX-provider based because the exact ONNX Runtime
   build is machine/distribution dependent. The acceptance gate is still the
   actual exposed provider, not the presence of a package name.
5. `faster-whisper --device amd` is rejected because Dictate only has CPU/CUDA
   coverage for that temporary backend.
6. Startup preflight blocks an explicit AMD request if the runtime cannot
   actually satisfy it, avoiding a silent CPU fallback.
7. `parakeet-tdt-0.6b-v3` is available as the planned multilingual Parakeet
   lane, but it still needs benchmark and packaging validation before promotion.
8. On Samuel's RTX 4090 workstation, `dictate doctor --stt-backend parakeet
   --device amd --quick` fails closed because no `MIGraphXExecutionProvider`,
   `ROCMExecutionProvider`, or `DmlExecutionProvider` is present. This is
   expected on this NVIDIA-only machine and does not validate the required AMD
   customer path.
9. `dictate doctor --stt-backend parakeet --device auto --quick` does not emit
   AMD-missing diagnostics on an NVIDIA-only machine; AMD readiness is checked
   strictly when `--device amd` is explicitly requested.
10. `scripts/windows-vm-smoke.sh --vm win11-dev --mode amd` validates the
    Windows DirectML packaging path by installing `.[amd]` in the Windows guest
    and requiring `DmlExecutionProvider` before running AMD doctor.

Benchmark evidence foundation:

1. `dictate benchmark` accepts plain ASR and diarized meeting runs.
2. JSON output records backend/model/device, WER, RTF, RTFx, peak RSS when the
   platform exposes it, per-sample hypotheses, optional speaker segments,
   diarization error rate, speaker-confusion rate, segment-boundary mean
   absolute error, boundary-pair counts, and promotion gate results.
3. Meeting lane benchmarks must use `--diarize --require-speaker-attribution`
   plus `--require-timestamp-metrics --require-der-metrics` and fixtures with
   timestamped `segments_json` references before any local Meeting backend is
   promoted.
4. `scripts/run-transcription-lane-benchmarks.sh` is the canonical local lane
   runner for writing the CPU, CUDA, CUDA multilingual, AMD, AMD multilingual,
   and Meeting JSON artifacts consumed by this plan and the plan audit. Use
   `--dry-run` first on target machines to verify the exact commands without
   loading models.
5. The canonical lane runner preflights each selected lane with `dictate doctor
   --quick` for the exact backend/model/device before benchmark work starts.
   This fails fast when CUDA, an AMD provider, or the gated Meeting speaker
   model is unavailable. `--skip-preflight` is reserved for intentionally
   collecting failed benchmark JSON artifacts.
6. `scripts/collect-transcription-evidence.sh` and
   `scripts/collect-transcription-evidence.ps1` package the plan, benchmark
   JSON artifacts, audit output, lane-runner dry-run output, per-lane doctor
   readiness output, and basic non-secret machine/provider context into a
   timestamped archive under
   `evidence-bundles/` for AMD, CUDA, Windows, and Meeting test-machine
   handoff. The plan audit requires that output directory to be ignored by Git.

## AMD GPU Path

AMD GPU support is essential. If CUDA is unavailable but an AMD GPU is present,
Dictate should still provide a high-performance local Parakeet path.

| Runtime Path | Platform | Plan |
| --- | --- | --- |
| ONNX Runtime `MIGraphXExecutionProvider` | Linux / ROCm | Primary Linux AMD target. |
| MIGraphX native API | Linux / ROCm | Fallback if ONNX Runtime packaging or operator coverage blocks Parakeet. |
| ONNX Runtime DirectML EP | Windows | Windows AMD evaluation path. |
| CPU Parakeet | All desktop OSes | Required fallback, not the desired high-performance AMD outcome. |

AMD acceptance gates:

1. Parakeet v2 and v3 load on the selected AMD runtime.
2. Unsupported operator fallback does not erase GPU benefit.
3. WER matches CPU/CUDA Parakeet within benchmark tolerance.
4. RTFx is materially better than CPU on representative AMD GPUs.
5. Packaging does not require non-technical users to compile ONNX Runtime.
6. Doctor/logs clearly report the AMD lane while the UI remains product-level.

The audit requires both AMD promotion artifacts before this lane can pass:
`benchmark-results/parakeet-v2-amd-human-gated.json` for English and
`benchmark-results/parakeet-v3-amd-human-gated.json` for multilingual. Each
artifact must use `device=amd`, be marked `fixture_class=curated-human`, have
no failed gates, include timestamp boundary evidence, include AMD/Radeon
hardware-provider provenance in the benchmark `environment`, and beat the CPU
RTFx baseline. Synthetic DirectML readiness remains package/provider evidence,
not representative Radeon performance evidence.

## Meeting Stack

Meeting mode is ASR plus speaker attribution over the same audio timeline.

Current foundation:

1. `SttCapabilities.supports_speaker_attribution` marks backends that can return
   speaker-attributed output.
2. WhisperX and the Parakeet speaker backends declare speaker-attribution
   support because they expose `transcribe_diarized(...)`.
3. `DictationEngine.transcribe(..., require_speaker_attribution=True)` fails
   closed instead of falling back to plain ASR.
4. `Daemon.start_meeting_recording()` and `stop_meeting_recording()` route
   meeting audio through the strict contract.
5. `POST /api/meetings/start` and `POST /api/meetings/stop` expose the backend
   surface for the desktop UI.
6. The capture home exposes a user-facing `Meeting` action that records through
   those strict meeting endpoints. Mock/dev mode returns speaker-labelled output
   so the flow is testable without a live engine.
7. `parakeet-pyannote` is a selectable local Meeting backend foundation. It
   uses Parakeet v2/v3 for ASR and pyannote Community-1 for speaker turns,
   supports `DICTATE_PYANNOTE_MODEL_PATH` for offline model checkouts, and uses
   `DICTATE_HF_TOKEN`, `HUGGINGFACE_HUB_TOKEN`, or `HF_TOKEN` for the gated
   Hugging Face model when no local path is configured. Source installers expose
   `--meeting` / `-Meeting` to install the pyannote/torch optional dependencies
   for this lane.
8. `TranscriptSegment` carries text, optional `t_start`/`t_end`, and optional
   `speaker_id`/`speaker_label` through the STT and engine result contract.
   Non-streamed `Record` and `Meeting` sessions now create durable note records,
   and Meeting captures can persist speaker-labelled timed segments in
   `NoteStore` while preserving the existing plain text transcript surface.
9. The live expanded-note UI renders speaker/timestamp segment rows when the
   backend provides them, and Markdown export preserves speaker labels and
   segment timing. Plain recordings continue to render/export as normal text.
10. The UI server rehydrates durable `NoteStore` records into the Notes list,
    including speaker/timestamp segment arrays, so a restarted UI can reopen a
    saved Meeting note with segment rows instead of only plain rolling history.
11. Notes list search, copy, and Markdown export use normalized segment text,
    speaker labels, speaker ids, and segment timestamps when a note carries
    structured segments. Plain notes continue to use the text-only path.
12. The loopback `Meeting` start endpoint now performs a speaker-attribution
    readiness check before capture starts. If the selected backend has no
    speaker-attribution capability, or if the `parakeet-pyannote` model access
    warning indicates the gated Community-1 model is unavailable, the API
    returns a product-level blocked state instead of recording audio that will
    later transcribe without speakers or fail generically.
13. Meeting mode now has a dedicated backend lane separate from normal
    dictation/plain recording. A fresh config can keep Parakeet v2 as the
    primary ASR backend while `Meeting` lazily installs and uses the default
    `parakeet-pyannote` speaker-attribution backend after readiness checks pass.
    Optional `meeting_stt_backend` and `meeting_stt_model` config keys can
    override that Meeting lane without changing push-to-talk or plain
    recording behavior.
14. Advanced testers can inspect the selected Meeting lane with `dictate config
    show` and set it without changing dictation via `dictate config
    set-meeting-model parakeet-pyannote/parakeet-tdt-0.6b-v2` or the v3 model.
15. DiariZen and NVIDIA Sortformer are now explicit selectable Meeting backend
    lanes as `parakeet-diarizen` and `parakeet-sortformer`. They share the same
    Parakeet ASR plus `TranscriptSegment` reconciliation contract and fail
    closed with runtime-readiness errors until their optional speaker
    attribution runtimes are installed.

This is not yet the finished Meeting product lane, but there is now one
curated-human local Meeting lane that passes the current speaker/timestamp
gates: `parakeet-sortformer` on CUDA. The local DiariZen lane still needs real
runtime loading, `parakeet-pyannote` still needs gated model access plus real
fixture benchmarks before it can become the CPU/offline fallback, and the
desktop UI still needs timestamp quality validation against broader real
fixtures.

The target architecture:

1. Parakeet produces transcript text and timestamps.
2. A speaker-attribution model assigns speaker turns.
3. Dictate reconciles ASR segments, word/segment timestamps, and speaker turns
   into one transcript stream.

## UI And App Wiring

The desktop UI must stay product-level while the engine lanes mature. The app
surface should continue to expose `Record`, push-to-talk dictation, notes, and
`Meeting`; model/provider names remain advanced configuration and diagnostics.

Current UI/backend wiring that belongs to this deployment:

1. Capture home, push-to-talk, and plain recording use the same non-meeting ASR
   path.
2. `Meeting` routes through strict meeting endpoints and fails closed when no
   speaker-attribution backend is available.
3. Durable notes can carry structured transcript segments with optional
   timestamps and speaker labels.
4. Expanded notes, list search, copy, and Markdown export understand structured
   segments while preserving the plain text path.
5. The UI server exposes live state, history/notes, config, doctor, and update
   routes over the loopback API used by the Tauri shell.
6. Mock/demo dictations are restricted to dev/test/browser preview mode or an
   explicit `VITE_DICTATE_ENABLE_MOCK=1` opt-in. A packaged shell with no live
   engine bridge must fail visibly instead of returning canned fixture text.

Remaining app-level gates:

1. Validate segment and speaker rendering against real meeting fixtures, not
   only mock/dev output.
2. Keep WhisperX visible only as an advanced/experimental backend while
   Parakeet speaker-attribution lanes are incomplete.
3. Staged update preparation is not in scope for this human-test release. The
   current live update route runs download and install together, and the
   Windows lifecycle smoke verifies that path.
4. Persistent skipped update versions are deferred with the staged update UX.
   The current UI-only `localStorage` skip remains a non-authoritative preview
   behavior until staged updates are promoted.
5. Dictate is local-only (`VISION.md`); there is no hosted provider lane to
   promote and no provider-key or switchable-backend UI.

## Speaker Attribution Lanes

| Lane | ASR | Speaker Attribution | Decision |
| --- | --- | --- | --- |
| Local GPU quality default | Parakeet v2/v3 | DiariZen | Selectable/preflightable as `parakeet-diarizen`; preferred if runtime benchmarks show processing time is bearable. |
| Local GPU live/speed | Parakeet v2/v3 | NVIDIA Streaming Sortformer v2.1 | Selectable/preflightable as `parakeet-sortformer`; use where responsiveness matters or DiariZen is too slow. |
| Local AMD GPU | Parakeet v2/v3 on AMD runtime | DiariZen / Sortformer if supported, otherwise pyannote fallback | Required benchmark lane. |
| Local CPU/offline fallback | Parakeet v2, or v3 if CPU benchmark passes | pyannote Community-1 | Initial backend exists as `parakeet-pyannote`; ship after packaging/licensing and benchmark gates pass. |

WhisperX is not the main meeting stack. Reuse timestamp/alignment ideas where
useful, but do not build the product dependency around WhisperX.

## Timestamping

All local systems should produce integrated timestamps. Parakeet v3 documents
word and segment timestamp support. The implementation should also study
WhisperX-style alignment/reconciliation patterns, but timestamping must be
owned by Dictate rather than depending on WhisperX as the product stack.

Benchmark timestamp quality separately from WER and DER:

1. Segment start/end error.
2. Word-level timing error where available.
3. Speaker-turn boundary error.
4. Stability on long recordings.

## Benchmark Requirements

Before promoting a lane to default, benchmark:

1. WER for transcript quality.
2. DER for speaker attribution where Meeting mode is involved.
3. Speaker-confusion rate separately from DER.
4. RTFx and live latency.
5. RAM/VRAM use.
6. First-run download size and install/package weight.
7. Runtime failure rate and fallback behavior.
8. Windows and Linux coverage where that lane is intended to ship.

The required artifact format is the `dictate benchmark --json-output ...`
report documented in `benchmarks/README.md`. Human-readable console output is
not enough for promotion because it cannot be compared reliably across hardware
lanes.

AMD GPU benchmark coverage is mandatory for the advanced local GPU tier. Test at
least one Linux ROCm/MIGraphX Radeon machine and one Windows AMD GPU path if
Windows packaging is in scope for that release.

## Human-Test Acceptance Checklist

The deployment is ready for human testing only when these checks are true:

1. **CPU English:** fresh install selects Parakeet v2, records real microphone
   speech, stores the note transcript, and does not repeat stale fixture text.
2. **NVIDIA English:** CUDA Parakeet v2 loads, doctor reports the CUDA provider,
   and benchmark RTFx is materially better than CPU on the same fixture set.
3. **NVIDIA multilingual:** Parakeet v3 loads on CUDA, exposes timestamp
   metadata where available, and passes multilingual fixture smoke tests.
4. **AMD English:** Parakeet v2 runs on the selected AMD execution path, and
   doctor/preflight clearly report the AMD provider instead of falling back
   silently to CPU.
5. **AMD multilingual:** Parakeet v3 either passes the same AMD gates or remains
   visibly blocked with a documented packaging/runtime reason.
6. **Meeting:** pressing `Meeting` produces speaker-attributed transcript output
   and durable speaker/timestamp segment metadata. If no speaker-attribution
   lane is available, the app must block the meeting path with a clear state
   rather than producing an undiarized transcript.
7. **Plain recording:** pressing `Record` uses the same ASR behavior as
   push-to-talk and does not expose speaker-attribution engine terms.
8. **Windows VM:** install, lifecycle, no-bundle build, and MSIX package smokes
   pass on `win11-dev`; the tested artifact paths are documented for human
   testers.
9. **Packaging:** the public Windows path is either a tested Store/MSIX route or
   an explicitly approved temporary artifact; no stale MSI/NSIS assumption is
   presented as ready.
10. **Regression:** focused Python tests for STT selection, model preparation,
    UI server state, tray helpers, Windows platform behavior, and meeting
    speaker-attribution rules pass locally.

Run `python3 scripts/transcription_plan_audit.py` before handing a build to a
tester. It summarizes which plan gates have local evidence and which are still
blocked. Use `--strict` in automation; it exits `2` while required promotion
evidence is missing.
Run `python3 scripts/transcription_plan_audit.py --readiness` for the
tester-facing checklist view. It maps the human-test acceptance items above to
the audit gates and currently marks CPU English, NVIDIA English, NVIDIA
multilingual, Meeting, plain recording, Windows VM, packaging, and regression
as `READY`, while AMD English and AMD multilingual remain `BLOCKED` until the
two Radeon promotion artifacts are imported. Use `--readiness --json` for a
machine-readable handoff report.
Use `scripts/run-human-test-readiness.sh --device auto` on Linux source
installs, or `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
scripts\run-human-test-readiness.ps1 -Device auto` on Windows source installs,
to print the readiness report, run a quick local Parakeet doctor, and show the
manual real-microphone checks that must be completed on each human-test
machine. These scripts intentionally print, rather than auto-pass, the
microphone checks because the acceptance condition is spoken human audio.

Latest focused backend regression evidence: `uv run pytest
tests/test_parakeet_pyannote_backend.py tests/test_stt_registry.py
tests/test_ui_server.py tests/test_daemon_history.py tests/test_engine_capabilities.py
-q` passed with `160 passed` on 2026-07-05.

Latest full Python regression evidence: `uv run pytest -q` passed with
`687 passed, 5 subtests passed` on 2026-07-05 after the UI mock-mode guard,
benchmark fixture tooling, preflighted lane runner, evidence collector,
validated AMD evidence importer, human-test readiness report and wrappers,
Windows MSIX, Windows AMD DirectML smoke, Meeting timestamp reconciliation, segment-aware UI refresh, and separate
Meeting backend-lane changes, including the DiariZen and Sortformer Meeting
lane registry additions and the source installer `--meeting` / `-Meeting`
optional dependency path.
`uv run python -m py_compile src/dictate/__main__.py src/dictate/benchmark.py
src/dictate/doctor.py src/dictate/stt/factory.py src/dictate/ui_server.py`
also succeeded on the same worktree.
Latest readiness-report evidence: `uv run pytest
tests/test_transcription_plan_audit.py tests/test_benchmark_fixtures.py -q`
passed with `30 passed` after adding the `--readiness` and `--readiness --json`
audit outputs plus source-install human-test readiness wrappers. On this current worktree,
`python3 scripts/transcription_plan_audit.py --readiness` reports every
human-test checklist item as `READY` except AMD English and AMD multilingual,
which remain `BLOCKED` on the missing Radeon benchmark artifacts.
`scripts/run-human-test-readiness.sh` and
`scripts/run-human-test-readiness.ps1` provide the source-install handoff
wrapper for that report plus the manual microphone and Meeting checks.
`scripts/run-human-test-readiness.sh --skip-doctor --device auto` prints the
readiness report and manual real-audio checks successfully. `bash -n
scripts/run-human-test-readiness.sh scripts/run-amd-promotion-benchmarks.sh
scripts/collect-transcription-evidence.sh scripts/windows-vm-smoke.sh` passed,
and `scripts/windows-vm-smoke.sh --vm win11-dev --mode syntax --timeout 900
--keep-guest-workdir` passed after parsing
`scripts/run-human-test-readiness.ps1` in the Windows guest.

Latest transcription-plan audit evidence: `python3
scripts/transcription_plan_audit.py` reports `pass` for the canonical plan,
benchmark fixture tooling, synthetic CUDA-vs-CPU comparison, synthetic
multilingual CUDA evidence, documented Windows VM package evidence covering
install, lifecycle, no-bundle build, AMD DirectML, and MSIX, and the explicit
staged-update deferral decision. It reports `pass` for CUDA human promotion
using the Open Speech Repository Harvard-sentence fixture:
`benchmark-results/parakeet-v2-cuda-human-gated.json` reports
`mean_wer=0.0500` and `mean_rtfx=36.65`, and
`benchmark-results/parakeet-v3-cuda-human-gated.json` reports
`mean_wer=0.3500` and `mean_rtfx=32.26`; both artifacts are marked
`fixture_class=curated-human` and pass WER, RTF, and timestamp gates. It
reports `pass` for Meeting speaker attribution because
`benchmark-results/parakeet-sortformer-cuda-human-meeting.json` is a
curated-human CUDA run with speaker attribution required and all DER,
speaker-confusion, and timestamp gates passing. It still records
`parakeet-pyannote` and `parakeet-diarizen` as remaining candidate blockers,
not as blockers to having one local Meeting lane ready for human testing. It
reports `blocked` for AMD Radeon performance because the required v2 English
and v3 multilingual curated-human AMD artifacts are missing. Synthetic DirectML
package readiness is not counted as representative Radeon performance evidence.
`python3
scripts/transcription_plan_audit.py --strict` exits `2` in this current state
because AMD Radeon performance artifacts are still missing.
Benchmark JSON reports now include ONNX Runtime provider names and detected GPU
summary lines where available, and the AMD gate rejects curated-human artifacts
that lack `MIGraphXExecutionProvider`/`ROCMExecutionProvider` or
`DmlExecutionProvider` plus AMD/Radeon hardware provenance.
`bash -n scripts/generate-curated-human-asr-fixture.sh
scripts/run-transcription-lane-benchmarks.sh`, `uv run pytest
tests/test_benchmark.py tests/test_transcription_plan_audit.py -q`
passed with `32 passed`, and `uv run python -m py_compile src/dictate/benchmark.py
scripts/transcription_plan_audit.py tests/test_benchmark.py
tests/test_benchmark_fixtures.py tests/test_transcription_plan_audit.py`
succeeded on 2026-07-05. `bash -n
scripts/windows-vm-smoke.sh scripts/transcription_plan_audit.py` also passed
after adding the audit test to
the Windows VM smoke selection.

Latest Parakeet-first local default evidence: `uv run pytest
tests/test_default_local_model.py tests/test_main_stt_selection.py
tests/test_stt_registry.py tests/test_parakeet_backend.py tests/test_ui_server.py
tests/test_main_benchmark_dispatch.py tests/test_model_prepare.py -q` passed
with `142 passed`; `uv run pytest tests/test_windows_platform.py
tests/test_main_benchmark_dispatch.py tests/test_default_local_model.py
tests/test_main_stt_selection.py tests/test_ui_server.py tests/test_stt_registry.py
-q` passed with `156 passed`; `uv run python -m py_compile
src/dictate/stt/factory.py src/dictate/__main__.py src/dictate/doctor.py
src/dictate/ui_server.py` succeeded; and `uv run dictate doctor --quick
--type-backend pynput` exited `0` with `STT backend: parakeet` and `STT model:
parakeet-tdt-0.6b-v2` on 2026-07-05. Fresh local startup defaults now choose
Parakeet v2 for CPU, CUDA, and AMD when the Parakeet runtime is importable;
faster-whisper remains an explicit or bridge fallback when Parakeet is
unavailable.

Latest Windows fresh-install Parakeet default evidence:
`scripts/windows-vm-smoke.sh --vm win11-dev --mode install --timeout 1800
--keep-guest-workdir` passed again on 2026-07-05 after the smoke expanded to
cover benchmark parser, benchmark dispatch, benchmark fixture-generator,
preflighted canonical lane-runner dry-run, evidence collector dry-run, and
stricter transcription-plan audit tests. The guest seeded
`%APPDATA%\dictate\config.yaml`, ran `314` focused Windows tests with
`16 skipped`, verified `dictate 2026.7.4`, and default
`dictate doctor --quick --type-backend pynput` reported `STT backend:
parakeet` with `STT model: parakeet-tdt-0.6b-v2`.
`scripts/windows-vm-smoke.sh --vm win11-dev --mode lifecycle --timeout 2400
--keep-guest-workdir` also passed again on 2026-07-05 after the preflighted
lane runner, stricter plan audit, refreshed install smoke, current package
checks, and refreshed AMD DirectML smoke: the install phase ran `196` focused
Windows tests with `15 skipped`, default doctor reported Parakeet v2, update
completed, and post-update doctor again reported Parakeet v2 before uninstall.
Staged update preparation is deferred out of the human-test release. The
human-test release uses the tested immediate source update path verified by the
same lifecycle smoke; staged update preparation and persistent skipped-version
state are post-human-test work.
After adding `tests.test_transcription_plan_audit` to the Windows guest
selection, the local matching command `uv run python -m unittest
tests.test_update_status tests.test_windows_platform tests.test_ui_server
tests.test_model_prepare tests.test_default_local_model
tests.test_main_stt_selection tests.test_stt_registry tests.test_benchmark
tests.test_main_benchmark_dispatch tests.test_benchmark_fixtures
tests.test_transcription_plan_audit tests.test_config_commands
tests.test_config_selection tests.test_daemon_history` also passed with `314
tests`.

Latest Windows package evidence: `scripts/windows-vm-smoke.sh --vm win11-dev
--mode build --timeout 1800 --keep-guest-workdir` passed on 2026-07-05 after
the validated AMD evidence import and segment-aware UI refresh. It rebuilt the
UI with Vite, froze and smoke-tested `dictate-engine.exe`, built
`dictate-ui-shell.exe` with `DICTATE_BUNDLES=no-bundle`, and verified both the
shell executable and `engine\dictate-engine.exe` sidecar. `scripts/windows-vm-smoke.sh
--vm win11-dev --mode msix --timeout 2400 --keep-guest-workdir` then passed on
the same current worktree after the same UI refresh: it rebuilt the UI and
engine sidecar, built the Tauri shell, packed the MSIX with Windows SDK
`makeappx.exe`, unpacked it, and validated the manifest, shell executable, logo
assets, and engine sidecar payload. Verified MSIX guest artifact:
`C:\Users\Public\dictate-vm-smoke\source\packaging\msix\out\ArcForgeDictate_2026.7.4.0_x64.msix`.

Latest structured segment evidence: `uv run pytest
tests/test_engine_capabilities.py tests/test_note_store.py
tests/test_daemon_history.py tests/test_parakeet_pyannote_backend.py -q`
passed with `101 passed` on 2026-07-05.

Latest benchmark evidence-format regression: `uv run pytest
tests/test_benchmark.py tests/test_main_benchmark_dispatch.py
tests/test_windows_platform.py tests/test_stt_registry.py -q` passed with
`59 passed` on 2026-07-05.

Latest UI evidence: `npm test -- --run` passed with `62 passed`, and
`npm run build` completed successfully from `ui/` on 2026-07-05.

Latest stale-fixture UI guard evidence: `npm test -- --run
src/test/ipc.test.js src/test/app.test.jsx` passed with `48 passed` from
`ui/`, and `npm run build` completed successfully on 2026-07-05. Coverage
verifies that a Tauri shell without an injected engine bridge is not mock mode,
does not seed demo history, and does not return the canned project-note
transcript.

Latest segment UI/export evidence: `uv run pytest tests/test_ui_server.py
tests/test_daemon_history.py tests/test_note_store.py -q` passed with
`123 passed`, and `npm test -- --run src/test/app.test.jsx
src/test/ipc.test.js` passed with `44 passed` from `ui/` on 2026-07-05.

Latest persisted segment rehydration evidence: `uv run pytest
tests/test_note_store.py tests/test_ui_server.py tests/test_daemon_history.py
-q` passed with `125 passed`, and `npm test -- --run src/test/app.test.jsx
src/test/ipc.test.js && npm run build` passed with `45 UI tests` plus a
successful production build from `ui/` on 2026-07-05.

Latest segment-aware notes search/export evidence: `npm test -- --run` passed
with `62 UI tests` from `ui/` on 2026-07-05. The suite now includes a
persisted Meeting note shaped like the curated Open Speech Repository fixture:
snake_case segment timestamps, speaker ids, speaker labels, and fractional
turn boundaries. Notes search can match segment-only text, the list preview
renders normalized speaker segment content instead of only a generic note
title, Markdown export preserves speaker labels and formatted timestamps, and
the expanded note renders the same real-fixture-style segment rows.

Latest Meeting start readiness evidence: `uv run pytest tests/test_ui_server.py
-q` passed with `51 passed`; `uv run python -m py_compile
src/dictate/ui_server.py` succeeded; and `npm test -- --run src/test/ipc.test.js
src/test/app.test.jsx && npm run build` passed with `45 UI tests` plus a
successful production build from `ui/` on 2026-07-05. The local API now blocks
Meeting before capture when the configured backend is not speaker-ready or when
pyannote Community-1 access is missing.

Latest non-meeting recording rule evidence: `uv run pytest
tests/test_daemon_history.py tests/test_provider_supervisor.py -q` passed with
`129 passed`, and `uv run python -m py_compile src/dictate/daemon.py`
succeeded on 2026-07-05. Note/plain recordings now use the same non-speaker ASR
path as push-to-talk, including the long-recording remote retry path. Meeting
remains the only recording mode that requests required speaker attribution.

Latest timestamp/DER benchmark-gate evidence: `uv run pytest
tests/test_benchmark.py tests/test_main_benchmark_dispatch.py -q` passed with
`12 passed`, and `uv run python -m py_compile src/dictate/benchmark.py`
succeeded on 2026-07-05. The
benchmark CLI now supports failing promotion gates for WER, RTF, DER, speaker
confusion, segment-boundary MAE, required timestamp metrics, and required DER
metrics. Runtime failures during benchmark transcription now write the requested
JSON artifact with a failed `benchmark_runtime` gate instead of producing only a
traceback.

Latest Parakeet timestamp-segment evidence: `uv run pytest
tests/test_parakeet_backend.py tests/test_engine_capabilities.py
tests/test_benchmark.py tests/test_main_benchmark_dispatch.py -q` passed with
`40 passed`; `uv run pytest tests/test_parakeet_backend.py
tests/test_parakeet_pyannote_backend.py tests/test_engine_capabilities.py
tests/test_benchmark.py tests/test_stt_registry.py -q` passed with `66 passed`;
and `uv run python -m py_compile src/dictate/stt/parakeet_backend.py
src/dictate/engine.py src/dictate/benchmark.py` succeeded on 2026-07-05.

Latest AMD packaging/readiness evidence: `uv lock` resolved the `amd` optional
extra and added `onnxruntime-directml==1.23.0`; `uv run pytest
tests/test_stt_registry.py tests/test_default_local_model.py
tests/test_main_stt_selection.py -q` passed with `64 passed` and verifies that
the DirectML extra exists for Windows `AMD64`, that explicit AMD readiness
errors point users to Windows DirectML or Linux ROCm/MIGraphX provider setup,
that `auto` mode does not incorrectly require an AMD provider on non-AMD
machines, and that saved AMD runtime profiles remain valid. `bash -n
scripts/windows-vm-smoke.sh install.sh scripts/generate-long-benchmark-fixtures.sh`
passed. `uv run python -m unittest tests.test_update_status
tests.test_windows_platform tests.test_ui_server tests.test_model_prepare
tests.test_default_local_model tests.test_main_stt_selection
tests.test_stt_registry tests.test_benchmark tests.test_main_benchmark_dispatch
tests.test_benchmark_fixtures tests.test_transcription_plan_audit
tests.test_config_commands tests.test_config_selection tests.test_daemon_history`
passed with `314 tests`; `uv run pytest
tests/test_stt_registry.py tests/test_default_local_model.py
tests/test_main_stt_selection.py tests/test_windows_platform.py -q` passed with
`103 passed`. `scripts/windows-vm-smoke.sh --vm win11-dev --mode amd --timeout
1800 --keep-guest-workdir` passed again on 2026-07-05 after the preflighted
lane runner, stricter plan audit, refreshed install smoke, and current package
checks: the guest seeded clean Dictate app data, ran `196` focused Windows tests
with `15 skipped`, installed `onnxruntime-directml==1.23.0`, reported
`providers=DmlExecutionProvider,CPUExecutionProvider`, and `dictate doctor
--stt-backend parakeet --device amd --quick --type-backend pynput` exited `0`
with `ONNX Runtime AMD-capable provider detected: DmlExecutionProvider`. This is
Windows DirectML packaging/readiness evidence; representative Radeon hardware
benchmarks are still required before AMD promotion.
`scripts/run-amd-promotion-benchmarks.sh` and
`scripts/run-amd-promotion-benchmarks.ps1` are now the canonical Radeon
test-machine wrappers for the remaining AMD promotion gate. On a machine with a
real AMD-capable ONNX Runtime provider they prepare the curated Open Speech
Repository ASR fixture when needed, run the English and multilingual AMD human
lanes, write `benchmark-results/parakeet-v2-amd-human-gated.json` and
`benchmark-results/parakeet-v3-amd-human-gated.json`, run the plan audit, and
can package the handoff bundle with `--collect-evidence` / `-CollectEvidence`.
The PowerShell wrapper is native for Windows Radeon/DirectML testers and does
not require Bash or FFmpeg for the curated ASR fixture. It installs `.[amd]` by
default so a Windows Radeon tester gets `onnxruntime-directml`; `-NoInstallAmdExtra`
is available only for pre-prepared virtual environments.
`scripts/import-transcription-evidence.py` imports returned Linux `.tar.gz` or
Windows `.zip` evidence bundles by copying `benchmark-results/*.json` into the
local repo and can rerun the audit with `--audit`, so the two AMD promotion
artifacts can be validated without manual file copying. It now validates each
candidate artifact as benchmark JSON with `config` and `summary` objects before
copying, supports evidence directories plus `.zip`, `.tar.gz`, and `.tgz`
bundles, and ignores unsafe archive member paths. `uv run pytest
tests/test_benchmark_fixtures.py tests/test_transcription_plan_audit.py -q`
passed with `27 passed` on 2026-07-05 after adding zip dry-run, tar import,
no-overwrite, malformed-JSON rejection, promotion-runner, and audit coverage.
`scripts/windows-vm-smoke.sh --vm win11-dev --mode syntax --timeout 900
--keep-guest-workdir` passed on 2026-07-05 after adding the wrapper to the
Windows syntax smoke, and the guest parsed
`scripts/run-amd-promotion-benchmarks.ps1` successfully. On this workstation,
ONNX Runtime exposes `TensorrtExecutionProvider`, `CUDAExecutionProvider`, and
`CPUExecutionProvider` only; `lspci` shows an AMD/ATI Raphael integrated VGA
device but no `MIGraphXExecutionProvider`, `ROCMExecutionProvider`, or
`DmlExecutionProvider`, so this machine still cannot produce representative AMD
promotion artifacts.

Latest local CUDA benchmark artifact evidence: `scripts/generate-benchmark-fixtures.sh`
generated a two-sample flite smoke manifest under `benchmark-fixtures/flite-smoke/`;
`uv run dictate benchmark --manifest benchmark-fixtures/flite-smoke/manifest.csv
--audio-root benchmark-fixtures/flite-smoke --stt-backend parakeet --model
parakeet-tdt-0.6b-v2 --device cuda --language en --require-timestamp-metrics
--max-mean-rtf 0.70 --max-mean-segment-boundary-mae-s 0.50 --json-output
benchmark-results/parakeet-v2-cuda-flite-smoke-gated.json --run-label
local-rtx4090-flite-smoke-gated` passed on 2026-07-05. The artifact reports
`mean_rtf=0.1433`, `mean_rtfx=10.78`, `mean_der=null`,
`mean_segment_boundary_mae_s=0.30`, and `segment_boundary_pair_count=4`; the
RTF, timestamp-MAE, and required timestamp metric gates passed. This is smoke
evidence only, not final curated WER or Meeting DER evidence.

Latest CPU-vs-CUDA Parakeet v2 comparison evidence:
`scripts/generate-long-benchmark-fixtures.sh` generated a longer synthetic
flite fixture under `benchmark-fixtures/flite-long/` with a 47.81s WAV and a
three-row repeat manifest. `uv run dictate benchmark --manifest
benchmark-fixtures/flite-long/manifest-3x.csv --audio-root
benchmark-fixtures/flite-long --stt-backend parakeet --model
parakeet-tdt-0.6b-v2 --device cpu --language en --require-timestamp-metrics
--max-mean-rtf 1.00 --max-mean-segment-boundary-mae-s 1.00 --json-output
benchmark-results/parakeet-v2-cpu-flite-long-3x-gated.json --run-label
local-cpu-flite-long-3x-gated` passed through the preflighted canonical lane
runner with `mean_rtf=0.0345`, `mean_rtfx=28.98`, `mean_wer=0.0976`, and
`mean_segment_boundary_mae_s=0.3830`. The same runner on CUDA, written to
`benchmark-results/parakeet-v2-cuda-flite-long-3x-gated.json`, passed with
`mean_rtf=0.0289`, `mean_rtfx=34.78`, `mean_wer=0.0976`, and the same
timestamp MAE. Both artifacts were refreshed on 2026-07-05 through
`scripts/run-transcription-lane-benchmarks.sh`, including lane preflight doctor
checks. This gives current same-fixture speed evidence for the NVIDIA lane on
the RTX 4090, but remains synthetic; curated human speech benchmarks are still
required before final product promotion.

Latest Parakeet v3 CUDA multilingual-lane evidence:
`scripts/run-transcription-lane-benchmarks.sh --lane cuda-multilingual` passed
on 2026-07-05 and wrote
`benchmark-results/parakeet-v3-cuda-flite-long-3x-gated.json`. The artifact
uses `model=parakeet-tdt-0.6b-v3`, `device=cuda`, and reports
`mean_rtf=0.0283`, `mean_rtfx=35.90`, `mean_wer=0.1301`,
`mean_segment_boundary_mae_s=0.2630`, and `segment_boundary_pair_count=6`.
This run included the Parakeet v3 CUDA preflight doctor and proves the wired v3
CUDA lane can produce timestamped benchmark output on the local NVIDIA
workstation. It remains synthetic English fixture evidence, not final
multilingual human-speech promotion evidence.

Latest long fixture and lane-runner reproducibility evidence: `bash -n
scripts/generate-long-benchmark-fixtures.sh scripts/generate-benchmark-fixtures.sh
scripts/generate-meeting-benchmark-fixtures.sh
scripts/run-transcription-lane-benchmarks.sh
scripts/collect-transcription-evidence.sh` passed, and `uv run pytest
tests/test_benchmark_fixtures.py -q` passed with `8 passed` on 2026-07-05. The
lane runner dry-run lists the canonical CPU, CUDA, multilingual CUDA, AMD,
multilingual AMD, and Meeting smoke artifact names before loading models, and
shows the preflight doctor commands that will fail fast for missing CUDA, AMD
provider, or gated Meeting model access. It also exposes explicit
`cuda-human`, `cuda-human-v3`, `amd-human`, `amd-human-v3`, `meeting-human`,
`meeting-diarizen-human`, and `meeting-sortformer-human` lanes that require
curated manifests through `DICTATE_HUMAN_MANIFEST` or
`DICTATE_MEETING_HUMAN_MANIFEST` and write artifacts marked
`fixture_class=curated-human`. `dictate benchmark --validate-manifest-only`
now validates curated-human manifests before model loading, rejecting generated
`benchmark-fixtures/` paths, `flite` sample IDs or filenames, missing audio
files, missing timestamp references, and missing timestamped speaker references
for Meeting/DER lanes. The Bash and PowerShell evidence collectors now include
`human-lane-dry-run.txt` with the exact curated-human CUDA, AMD, and Meeting
promotion commands plus `promotion-status.txt` showing whether each required
promotion artifact is present or missing. The collector dry-runs list the
handoff bundle contents without exposing token or environment-variable values
and include `lane-readiness.txt` with quick doctor output for CPU, CUDA, AMD,
pyannote, DiariZen, and Sortformer lanes. The default `evidence-bundles/`
output path is ignored by Git.
`scripts/windows-vm-smoke.sh --vm win11-dev --mode syntax --timeout 900
--keep-guest-workdir` also passed again on 2026-07-05 after the collector
promotion-status changes and parsed `scripts/collect-transcription-evidence.ps1`
in the Windows guest.

Latest curated-human Meeting fixture evidence:
`scripts/generate-curated-human-meeting-fixture.sh` creates
`benchmark-curated/open-speech-meeting/manifest.csv` from two Open Speech
Repository Harvard-sentence speakers with timestamped `Speaker 1` and
`Speaker 2` turns. `uv run python -m dictate benchmark --manifest
benchmark-curated/open-speech-meeting/manifest.csv --audio-root
benchmark-curated/open-speech-meeting --stt-backend parakeet-pyannote --model
parakeet-tdt-0.6b-v2 --device cuda --fixture-class curated-human --diarize
--require-speaker-attribution --require-timestamp-metrics
--require-der-metrics --validate-manifest-only` passed on 2026-07-05. This
proves the curated-human Meeting manifest is valid and ready for the three
Meeting runtime lanes; it does not prove speaker-attribution runtime quality
until `parakeet-pyannote`, `parakeet-diarizen`, or `parakeet-sortformer` can
load and write their `*-cuda-human-meeting.json` artifacts.
The curated-human Meeting candidate benchmarks were also run so they could
write comparable candidate artifacts:
`benchmark-results/parakeet-pyannote-cuda-human-meeting.json` and
`benchmark-results/parakeet-diarizen-cuda-human-meeting.json` are marked
`fixture_class=curated-human` and still fail `benchmark_runtime` on the same
curated-human Meeting sample. The pyannote lane needs accepted
`pyannote/speaker-diarization-community-1` terms plus a Hugging Face token or
offline model checkout; the DiariZen lane needs an importable DiariZen runtime.
`benchmark-results/parakeet-sortformer-cuda-human-meeting.json` is now a real
curated-human CUDA run: NeMo ASR imports, the NVIDIA Streaming Sortformer v2.1
model loads from the Hugging Face cache, and diarization inference runs. After
correcting the OSR meeting fixture to use the actual Harvard sentences in the
audio and speech-only sentence timestamps, and after changing benchmark speaker
metrics to score by timestamp overlap rather than segment index,
`meeting-sortformer-human` passes the current Meeting gates with
`mean_rtfx=3.00`, `mean_wer=0.2200`, `mean_der=0.1920`,
`mean_speaker_confusion_rate=0.0867`, and
`mean_segment_boundary_mae_s=0.2258`.

Latest meeting fixture evidence: `scripts/generate-meeting-benchmark-fixtures.sh`
generated `benchmark-fixtures/flite-meeting-smoke/manifest.csv` with one
two-speaker synthetic meeting WAV, three timestamped speaker turns, and
`segments_json` references; `uv run pytest tests/test_benchmark_fixtures.py
tests/test_benchmark.py tests/test_main_benchmark_dispatch.py -q` passed on
2026-07-05. These fixtures are smoke evidence only; curated human meeting
recordings are still required before promoting a Meeting speaker-attribution
lane.

Latest `parakeet-pyannote` meeting benchmark attempt: `uv run dictate benchmark
--manifest benchmark-fixtures/flite-meeting-smoke/manifest.csv --audio-root
benchmark-fixtures/flite-meeting-smoke --stt-backend parakeet-pyannote --model
parakeet-tdt-0.6b-v2 --device cuda --language en --diarize
--require-speaker-attribution --require-timestamp-metrics --require-der-metrics
--max-mean-der 0.20 --max-mean-segment-boundary-mae-s 0.50
--max-mean-speaker-confusion-rate 0.15 --json-output
benchmark-results/parakeet-pyannote-cuda-flite-meeting.json --run-label
local-rtx4090-flite-meeting-gated` exited with code `2` on 2026-07-05 and
wrote the JSON artifact. The failed `benchmark_runtime` gate records that
pyannote Community-1 still needs either accepted Hugging Face model terms plus
`DICTATE_HF_TOKEN`/`HUGGINGFACE_HUB_TOKEN`/`HF_TOKEN`, or an offline
`DICTATE_PYANNOTE_MODEL_PATH` checkout. This proves the benchmark wiring reaches
the real meeting backend, but the local meeting lane is not promotion-ready.

Latest DiariZen/Sortformer meeting benchmark attempts:
`scripts/run-transcription-lane-benchmarks.sh --lane meeting-diarizen
--skip-preflight` and `scripts/run-transcription-lane-benchmarks.sh --lane
meeting-sortformer --skip-preflight` both exited with code `2` on 2026-07-05
and wrote `benchmark-results/parakeet-diarizen-cuda-flite-meeting.json` and
`benchmark-results/parakeet-sortformer-cuda-flite-meeting.json`. The failed
`benchmark_runtime` gates record that the DiariZen runtime is not importable.
Sortformer has since moved past the missing-runtime blocker through the
`sortformer` optional dependency group in `pyproject.toml`, which installs NeMo
ASR with compatible `transformers`/`tokenizers` pins. `uv run python -m dictate
doctor --stt-backend parakeet-sortformer --model parakeet-tdt-0.6b-v2 --device
cuda --quick --type-backend pynput` now exits `0` on the RTX 4090 workstation.
The curated-human Sortformer benchmark runs and writes DER/timestamp metrics
and now passes the current quality gates on the OSR meeting fixture, so it is
the first local Meeting lane promoted for human testing. It still needs broader
meeting fixtures before becoming the long-term default.

Latest `parakeet-pyannote` preparation evidence: `uv run pytest
tests/test_model_prepare.py tests/test_parakeet_pyannote_backend.py
tests/test_main_prepare_dispatch.py -q` passed with `20 passed`, and `uv run
python -m py_compile src/dictate/model_prepare.py
src/dictate/stt/parakeet_pyannote_backend.py` succeeded on 2026-07-05. `uv run
dictate prepare-model --stt-backend parakeet-pyannote --model
parakeet-tdt-0.6b-v2 --device cuda --compute-type int8` now reaches the real
meeting preparation path: Parakeet CUDA loads, then preparation exits with code
`2` because pyannote Community-1 model access still needs accepted Hugging Face
terms plus a token or an offline model path.

Latest Meeting timestamp reconciliation evidence: `uv run pytest
tests/test_parakeet_pyannote_backend.py tests/test_engine_capabilities.py
tests/test_benchmark.py tests/test_main_benchmark_dispatch.py
tests/test_transcription_plan_audit.py -q` passed with `48 passed`, and `uv
run python -m py_compile src/dictate/stt/parakeet_pyannote_backend.py
tests/test_parakeet_pyannote_backend.py` succeeded on 2026-07-05. The
`parakeet-pyannote` backend now uses Parakeet ASR subsegment timestamps inside
pyannote speaker turns when available, offsets them into the original meeting
timeline, clamps speaker turns to the actual audio duration, and falls back to
one speaker-labelled segment per turn when only plain ASR text is available.

Latest separate Meeting backend-lane evidence: `uv run pytest
tests/test_daemon_history.py tests/test_ui_server.py tests/test_config_selection.py
tests/test_default_local_model.py tests/test_main_stt_selection.py -q` passed
with `181 passed`, and `uv run python -m py_compile src/dictate/config.py
src/dictate/daemon.py src/dictate/ui_server.py tests/test_daemon_history.py
tests/test_ui_server.py` succeeded on 2026-07-05. This verifies that normal
note/plain recording continues to use the primary ASR backend, while Meeting
can use a dedicated speaker-attribution backend and the UI start endpoint
selects the default `parakeet-pyannote` Meeting lane even when the primary
dictation backend is plain Parakeet.

Latest Meeting-lane configuration evidence: `uv run pytest
tests/test_config_commands.py tests/test_config_selection.py tests/test_ui_server.py
tests/test_daemon_history.py tests/test_main_stt_selection.py -q` passed with
`192 passed`, and `uv run python -m py_compile src/dictate/config.py
src/dictate/__main__.py tests/test_config_commands.py tests/test_config_selection.py`
succeeded on 2026-07-05. This verifies `meeting_stt_backend` /
`meeting_stt_model` config parsing, `dictate config show` reporting the Meeting
lane, and `dictate config set-meeting-model ...` changing the Meeting lane
without changing the primary dictation backend.

Latest DiariZen/Sortformer lane scaffolding evidence: `uv run pytest
tests/test_stt_registry.py tests/test_ui_server.py tests/test_windows_platform.py
tests/test_model_prepare.py tests/test_benchmark_fixtures.py
tests/test_transcription_plan_audit.py -q` passed with `131 passed`, and `uv
run python -m py_compile src/dictate/stt/base.py src/dictate/stt/factory.py
src/dictate/stt/__init__.py src/dictate/stt/parakeet_speaker_backend.py
src/dictate/doctor.py src/dictate/ui_server.py src/dictate/windows_control.py`
succeeded on 2026-07-05. `scripts/windows-vm-smoke.sh --vm win11-dev --mode
syntax --timeout 900 --keep-guest-workdir` also passed and parsed the updated
PowerShell evidence collector in the Windows guest. `parakeet-diarizen` and
`parakeet-sortformer` are now registered speaker-attribution Meeting lanes,
exposed to doctor/model selection, Windows control defaults, UI model state,
model preparation, and the canonical lane-runner dry-run. The DiariZen lane
intentionally fails readiness until its runtime is installed. The Sortformer
lane now passes runtime readiness when the `sortformer` optional dependency
group is installed and has a passing curated-human benchmark artifact. Meeting
still fails closed instead of silently returning undiarized output when the
selected lane is unavailable.

Latest Meeting installer-extra evidence: `bash -n install.sh install-windows.ps1`
passed, and `uv run pytest tests/test_windows_platform.py
tests/test_stt_registry.py -q` passed on 2026-07-05. Linux source installs now
accept `--meeting` / `--no-meeting` and `DICTATE_INSTALL_MEETING=1`; Windows
source installs accept `-Meeting`. Both install paths add the existing
`meeting` optional dependency group for the `parakeet-pyannote` lane.
Sortformer runtime setup is captured as the explicit `sortformer` optional
dependency group for CUDA tester machines; DiariZen remains external runtime
setup until a stable package/install path is selected.

Latest Meeting backend readiness evidence: no `DICTATE_HF_TOKEN`,
`HUGGINGFACE_HUB_TOKEN`, `HF_TOKEN`, `DICTATE_PYANNOTE_MODEL_PATH`, or
`DICTATE_PYANNOTE_MODEL` is configured on this workstation, and no local
Community-1 checkout was found under the shallow home-directory search. `uv run
pytest tests/test_stt_registry.py tests/test_ui_server.py
tests/test_model_prepare.py -q` passed with `76 passed`; `uv run python -m
py_compile src/dictate/stt/factory.py src/dictate/ui_server.py
src/dictate/model_prepare.py` succeeded; and `uv run dictate doctor
--stt-backend parakeet-pyannote --device cuda --quick` exited with code `2` on
2026-07-05, reporting the missing gated pyannote model access as `[FAIL]`.

## Implementation Phases

1. **Consolidate defaults**
   - Keep fresh CPU English installs on Parakeet v2.
   - Keep recordings and push-to-talk on the same ASR path.
   - Keep Meeting as the only path that requires speaker attribution.

2. **Parakeet runtime coverage**
   - Wire Parakeet v2 CUDA.
   - Wire Parakeet v3 CUDA.
   - Benchmark Parakeet v3 CPU feasibility.
   - Build AMD GPU runtime probe and prototype with MIGraphX/ROCm.
   - Evaluate Windows AMD DirectML/MIGraphX packaging.

3. **Meeting speaker attribution**
   - Validate DiariZen runtime loading and benchmark `parakeet-diarizen`.
   - Broaden NVIDIA Streaming Sortformer v2.1 benchmarks beyond the initial
     passing curated-human OSR fixture.
   - Benchmark and package the initial `parakeet-pyannote` Community-1 wrapper.
   - Finish Dictate timestamp/speaker-turn reconciliation in the UI/export
     surfaces and benchmark timestamp quality.

4. **Remove Whisper product dependency**
   - Keep current faster-whisper code only while Parakeet coverage is incomplete.
   - Remove Whisper/faster-whisper from product lanes after Parakeet CPU, CUDA,
     AMD, multilingual, timestamp, and packaging gates pass.
   - Keep benchmark comparison rows as historical evidence only.

## Model Landscape Review (2026-09-20)

Periodic check of the open STT landscape against the lanes above. Numbers are
from the Open ASR Leaderboard English short-form track (cleaned datasets, so
they are not comparable to pre-2026 snapshots). RTFx is the leaderboard's GPU
figure and only useful as a relative ordering.

| Model | WER | RTFx | Params | License | Relevance to Dictate |
| --- | --- | --- | --- | --- | --- |
| Qwen/Qwen3-ASR-1.7B | 4.31 | 820 | 1.7B | Apache-2.0 | 52 languages, LLM decoder. GPU-class accuracy option only. |
| nvidia/canary-qwen-2.5b | 4.43 | 867 | 2.5B | CC-BY-4.0 | GPU-class. |
| ibm-granite/granite-speech-4.1-2b | 4.62 | 546 | 2B | Apache-2.0 | `-plus` variant does speaker-attributed ASR with word timestamps; Meeting prototype candidate. |
| CohereLabs/cohere-transcribe-03-2026 | 4.67 | 907 | 2B | Apache-2.0 | Open weights now; community ONNX exists. GPU-class. |
| **nvidia/parakeet-tdt-0.6b-v2 (shipped default)** | **4.70** | **6025** | 0.6B | CC-BY-4.0 | Best accuracy-per-speed of any open model. Keep. |
| nvidia/parakeet-tdt-0.6b-v3 (shipped multilingual) | 4.86 | 6076 | 0.6B | CC-BY-4.0 | Keep. |
| ibm-granite/granite-speech-5.0-470m-turboctc | 5.04 | 12946 | 0.47B | Apache-2.0 | Released 2026-08-25. 2x Parakeet throughput, English only, CTC with no timestamps, needs transformers>=5.16 or community ONNX. Watch. |
| nvidia/nemotron-speech-streaming-en-0.6b | 5.25 | 1167 | 0.6B | NVIDIA Open | Cache-aware streaming, 80 ms-1.1 s chunks. Streaming candidate. |
| distil-whisper/distil-large-v3.5 | 5.40 | 879 | 0.8B | MIT | Better than our faster-whisper `turbo` (6.36) at the same speed, English only. Added as a selectable bridge model (`distil-large-v3.5`), not the default. |
| openai/whisper-large-v3-turbo (faster-whisper `turbo`) | 6.36 | 797 | 0.8B | MIT | Bridge lane only. |
| nvidia/nemotron-3.5-asr-streaming-0.6b | 7.88 | 1345 | 0.6B | OpenMDW-1.1 | 40 locales, streaming. Multilingual streaming candidate; accuracy below v3. |

### Parakeet Unified 0.6b evaluation

`nvidia/parakeet-unified-en-0.6b` (2026-04-07) is a FastConformer-RNNT that
runs offline and streaming (down to 160 ms) from one checkpoint. NVIDIA claims
it beats `parakeet-tdt-0.6b-v2` offline. It was evaluated on 2026-09-20 on a
16-core CPU workstation, int8, as a possible v2 successor, using two community
ONNX exports (an onnx-asr layout and the k2/sherpa-onnx maintainer's export)
so the export was not the variable. Fixtures: 8 LibriSpeech test-clean clips
(216 reference words, 79 s) and the repo's `open-speech-harvard` fixture
(`scripts/generate-curated-human-asr-fixture.sh`, 80 words, peak level 0.34).

| Fixture | v2 int8 (onnx-asr) | unified int8 (onnx-asr) | unified int8 (sherpa-onnx) |
| --- | --- | --- | --- |
| LibriSpeech, 16 kHz, clean | 0.46% | 0.46% | 0.46% |
| LibriSpeech through an 8 kHz round-trip | 0.46% | 0.46% | - |
| LibriSpeech + white noise, 20 / 10 / 5 dB SNR | 0.46 / 0.46 / 0.46% | 0.93 / 1.39 / 1.39% | - |
| Harvard fixture, native level (peak 0.34) | 3.75% | 23.75% | 47.50% |
| Harvard fixture, peak-normalised to 0.90 | 5.00% | 8.75% | - |
| Harvard fixture, attenuated to peak 0.09 | 6.25% | 28.75% | - |
| CPU RTFx on LibriSpeech (same loaded machine) | 4.5 | 3.2 | 3.5 |

Findings:

1. On clean, well-levelled audio unified matches v2 exactly.
2. Unified is strongly input-level sensitive; v2 is not. Peak-normalising the
   Harvard fixture takes unified from 23.75% to 8.75%, still more than twice
   v2. Dictate's always-on AGC (`audio_preprocess.py`, target -18 dBFS RMS)
   would narrow but not close that gap.
3. Unified degrades under additive noise where v2 does not.
4. Unified is roughly 30% slower than v2 on CPU int8 with no accuracy gain.
5. Streaming needs the sherpa-onnx runtime; onnx-asr has no streaming path.

Decision: `parakeet-tdt-0.6b-v2` stays the English default. Unified is a
streaming-lane candidate only, to be revisited if live-text-while-holding-key
becomes a product goal, and then together with `nemotron-speech-streaming` and a
sherpa-onnx backend decision. Any such evaluation must include quiet-input and
noisy-input fixtures, not only clean read speech.

### Runtime notes

1. `onnx-asr` 0.12.0 (2026-07-15) adds convolution-based ONNX preprocessors for
   the GPU path.
2. ONNX Runtime is now pinned to `1.30.x` for both the CPU and CUDA lanes.
   `onnxruntime-gpu` 1.27+ ships CUDA 13 runtime wheels (`nvidia-cuda-runtime`,
   `nvidia-cudnn-cu13`), which need NVIDIA driver 580 or newer; 1.26 was the
   last CUDA 12 build. The old `<1.24` pin existed for the external-data path
   check; Dictate stages Parakeet as flat real files, and an external-data
   model loads on 1.30 (verified 2026-09-20 on CPU). CUDA execution on 1.30
   still needs a `dictate doctor --stt-backend parakeet --device cuda` pass
   on NVIDIA hardware before the GPU lane is called re-validated.
3. `onnxruntime-directml` stopped at 1.24.4; the `amd` extra is capped at
   `<1.25`. Microsoft has retired that wheel, so the Windows AMD lane needs a
   replacement runtime decision (ORT's WinML/DirectML EP plugin or ROCm).
4. `sherpa-onnx` 1.13.8 supports Parakeet Unified (offline and streaming),
   Nemotron streaming, Moonshine, Qwen3-ASR, and Cohere Transcribe. It is the
   runtime to evaluate if a streaming lane is opened.
5. `pyannote.audio` 4.0.7 is the current Community-1 runtime.

## Archived Notes

Archived notes are reference material only. They do not override this plan.

| Archived Note | Reason |
| --- | --- |
| `docs/archive/dictate-pro-subscription-architecture-2026-07-05.md` | Historical paid subscription and hosted-meeting architecture; the current model and meeting deployment plan lives here. |
| `docs/archive/goals-2026-07-05.md` | Superseded as the planning landing page; retained for historical product/release notes. |
| `docs/archive/frontend-wiring-2026-07-05.md` | Superseded by the UI and app wiring section in this plan. |
| `docs/archive/meeting-transcription-research-2026-07-05.md` | Superseded by this consolidated plan. |
| `docs/archive/recent-dictation-history-spec-2026-07-05.md` | Historical implementation spec; local notes/history is now implementation context, not the active deployment goal. |
| `docs/archive/xai-diarization-cost-model-2026-07-05.md` | Cost-focused provider note; no longer the canonical model direction. |

## Sources

- Open ASR Leaderboard paper/table: https://arxiv.org/html/2510.06961v4
- Parakeet v2 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
- Parakeet v3 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Canary/Parakeet v3 technical report: https://arxiv.org/abs/2509.14128
- pyannote Community-1 model card: https://huggingface.co/pyannote/speaker-diarization-community-1
- Diarization benchmark paper: https://arxiv.org/html/2509.26177v1
- NVIDIA Streaming Sortformer blog: https://developer.nvidia.com/blog/identify-speakers-in-meetings-calls-and-voice-apps-in-real-time-with-nvidia-streaming-sortformer/
- ONNX Runtime MIGraphX Execution Provider: https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html
- ONNX Runtime ROCm Execution Provider note: https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html
- AMD ROCm ONNX Runtime install notes: https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-onnx.html
- AMD GPUOpen DirectML/ONNX Runtime guide: https://gpuopen.com/learn/onnx-directlml-execution-provider-guide-part1/
