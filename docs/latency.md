# Dictation latency

The product measure in `VISION.md` is the time from releasing the shortcut to
text appearing, on everyday CPU machines. This page says how to measure it
without a person or a microphone, and records the first baseline.

## How to measure

```bash
uv sync
DICTATE_PARAKEET_MODEL_PATH=/usr/lib/Dictate/engine/models/parakeet-tdt-0.6b-v2-onnx \
  uv run python scripts/measure_dictation_latency.py --json latency.json
```

`scripts/measure_dictation_latency.py` drives the real `Daemon` object through
the path that runs after key release:

1. `Daemon._on_hotkey_release()` calls `recorder.stop()`. A scripted recorder
   stands in for the microphone. It ran the real `AudioPreprocessor` (gain
   control and WebRTC noise suppression) over the utterance in 20 ms blocks
   while "the user was talking", and on stop it flushes the preprocessor tail,
   as `SoundDeviceRecorder.stop()` does.
2. The final chunk goes on the daemon's queue and the transcription worker
   thread picks it up.
3. `DictationEngine.transcribe()` calls `ParakeetSpeechToText.transcribe_segments()`:
   mel features, the ONNX encoder, then the TDT decoder loop (one ONNX call per
   step).
4. Lexicon post-correction (the harness uses `post` mode with a 30-word
   vocabulary so this stage does real work; `--lexicon-mode native` is the
   shipped default and skips it).
5. `HistoryStore.append()` in a temp dir, seeded to its full 20 entries.
6. `output.send()`, replaced by a no-op that records the time.

No hotkey listener starts and nothing is typed. Each stage is timed with
`time.perf_counter()`.

- **Cold** is the first dictation in a fresh process, right after the model
  loads. The daemon preloads the model at startup, so model load is reported
  separately and is not part of release latency.
- **Warm** is every dictation after that, in one process, round-robin across
  lengths.
- Before each release the harness idles 0.5 s, then releases at a point spread
  evenly across the worker's 100 ms queue-poll cycle, as real key presses land.
- Utterances are synthesised with ffmpeg's flite voice (as the other fixture
  scripts do): short 2.6 s, medium 9.1 s, long 29.9 s. They go to
  `benchmark-fixtures/latency/` by default.

Probes for the levers below (they change only the harness, not the product):
`--intra-op-threads N` sets ONNX Runtime intra-op threads, and
`--pad-silence-s S` adds S seconds of silence before and after each utterance.

Read the numbers alongside load average. The script prints load before and
after each run because ONNX Runtime latency moves a lot with other CPU work.

## Baseline (2026-10-01, Parakeet TDT 0.6b v2 int8, ONNX Runtime 1.30.0, CPU)

Release-to-output latency in ms, as median / p90. The shipped thread settings
are in effect: `intra_op_num_threads=0` and `inter_op_num_threads=0` (ONNX
Runtime picks), sequential execution, `ORT_ENABLE_ALL`. The process grows from
33 to 312 threads at model load on X Forge, and from 9 to 72 on the VM.

| Machine | Load avg (1 min) | Short 2.6 s cold | Short warm | Medium 9.1 s cold | Medium warm | Long 29.9 s cold | Long warm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X Forge, Ryzen 9 7950X, 32 threads, run A | 6 to 12 | 310 / 324 | 292 / 409 | 657 / 751 | 686 / 874 | 1710 / 1756 | 2051 / 2710 |
| X Forge, run B | 23 to 35 | 383 / 396 | 414 / 494 | 703 / 717 | 694 / 911 | 2269 / 2274 | 1981 / 2484 |
| win11-gpu WSL2 VM, 8 vCPU of the same 7950X | 0.2 to 2.6 | 224 / 251 | 212 / 237 | 432 / 484 | 440 / 515 | 1391 / 1422 | 1206 / 1378 |

n = 3 cold processes and 10 warm runs per length (5 for long). Model load at
startup: 1.8 s median on X Forge, 2.5 to 3.6 s on the VM.

Both machines are the same CPU. The VM is a nested slice of X Forge, which was
also running a PyInstaller build, other agents' work and two VMs during these
runs. So this is one CPU at two core counts and two contention levels, not two
different CPUs. The Framework laptop, the second daily machine, was not
reachable and is not measured.

### Where the time goes (warm medians, ms)

| Stage | X Forge A short / medium / long | VM short / medium / long |
| --- | --- | --- |
| Recorder stop and preprocessor flush | 0 / 0 / 1 | 0 / 0 / 1 |
| Queue handoff to the worker | 50 / 38 / 57 | 56 / 58 / 42 |
| Mel features | 2 / 10 / 18 | 1 / 4 / 17 |
| Encoder (ONNX) | 237 / 619 / 1836 | 138 / 350 / 1068 |
| TDT decoder loop | 7 / 16 / 52 | 5 / 11 / 37 |
| Post-correction | 0 / 1 / 4 | 0 / 1 / 4 |
| History append | 1 / 1 / 1 | 1 / 1 / 1 |

- The encoder is 75 to 90% of the latency, and it scales with audio length
  (about 35 to 55 ms per second of audio on the VM).
- The queue handoff is a fixed 0 to 100 ms (median about 50) on every
  dictation. The worker waits on the partial-chunk queue with
  `get(timeout=0.1)` and only checks the final-chunk queue between waits
  (`Daemon._transcription_loop`), so a final chunk sits until the timeout runs
  out. That is about 20% of a short dictation.
- Cold and warm are the same within noise. Because the daemon preloads the
  model, the first dictation pays no extra cost.
- Everything else, including post-correction and the history write, is under
  10 ms.

## Levers (measured, not implemented)

1. **Wake the worker as soon as the final chunk is queued.** This saves about
   50 ms median and up to 100 ms on every dictation, with no effect on the
   transcript.
2. **Set ONNX Runtime threads explicitly.** On busy X Forge, setting
   `--intra-op-threads 4` brought warm latency to 240 ms short, 546 ms medium
   and 1404 ms long, against 292 to 414, 686 to 694 and 1981 to 2051 ms with
   the default. 8 threads gave 257, 488 and 1363 ms. An earlier sweep at
   similar load gave the same result: 4, 8 and 16 explicit threads were all
   about 2x faster than the default. On the idle 8-vCPU VM the default
   (8 threads) was best: 4 threads gave 260, 578 and 1776 ms, and 2 threads gave
   297, 682 and 2167 ms. A likely cause is that the default thread pool pins
   one thread per physical core. When other work holds those cores, the pinned
   threads stall. Next steps: try explicit physical-core counts without
   pinning, and with spin-wait off, on the Framework laptop and a 4-core
   machine.
3. **Trim leading and trailing silence before decode.** The encoder pays for
   every second it is given. Adding 1 s of silence to each end of the short
   utterance raised warm latency from 212 to 277 ms on the VM, and from 292 to
   461 ms on loaded X Forge. Real push-to-talk captures carry some of this
   lead-in and tail. Trimming needs a conservative energy or VAD gate so it
   cannot clip the first or last word.

## Not measured

- The real output backend (`wl-copy` or `xclip` followed by a paste shortcut,
  or `xdotool type`). The harness does not type into the desktop. Each backend
  starts at least one subprocess.
- PortAudio stream stop and close time inside `SoundDeviceRecorder.stop()`.
  Measuring it needs a live input device.
- The Framework laptop. Windows-native runs (the VM numbers come from WSL2
  Linux).
