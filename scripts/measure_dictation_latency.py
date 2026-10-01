#!/usr/bin/env python3
"""Measure push-to-talk latency from key release to the output call, on CPU.

No microphone, no keyboard, no human. Recorded utterances are fed through the
same objects the daemon uses after the shortcut is released:

    Daemon._on_hotkey_release()
      -> recorder.stop()            (a scripted recorder; flushes the real
                                     AudioPreprocessor tail, like the live one)
      -> final-chunk queue -> transcription worker thread
      -> DictationEngine.transcribe() -> ParakeetSpeechToText.transcribe_segments()
           -> features (mel) -> encoder (ONNX) -> TDT decoder loop (ONNX per step)
      -> lexicon post-correction
      -> HistoryStore.append()      (temp dir, seeded to its steady-state size)
      -> output.send()              (no-op that only records the time)

Capture-time preprocessing (AGC + WebRTC noise suppression) runs while the user
is still talking, so it is timed separately and is not part of the release
latency; only its flush is.

Each stage is timed with time.perf_counter(). "Cold" is the first dictation in
a fresh process right after the model has loaded (the daemon preloads the model
at startup, so model load itself is reported separately, not as latency).
"Warm" is every dictation after that.

Utterances are synthesised with ffmpeg's flite voice (the same TTS the
benchmark fixture scripts use) unless --fixtures-dir already holds them.

Example:
    DICTATE_PARAKEET_MODEL_PATH=/usr/lib/Dictate/engine/models/parakeet-tdt-0.6b-v2-onnx \\
        uv run python scripts/measure_dictation_latency.py --json latency.json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from dictate.audio_preprocess import create_preprocessor  # noqa: E402
from dictate.daemon import Daemon  # noqa: E402
from dictate.history import MAX_ENTRIES, HistoryStore  # noqa: E402
from dictate.note_store import NoteStore  # noqa: E402
from dictate.stt.parakeet_backend import (  # noqa: E402
    PARAKEET_MODEL_PATH_ENV,
    ParakeetSpeechToText,
)

SAMPLE_RATE = 16000
INSTALLED_MODEL = Path("/usr/lib/Dictate/engine/models/parakeet-tdt-0.6b-v2-onnx")
# Callback block the scripted capture feeds the preprocessor (PortAudio picks
# its own; 20 ms is typical for Pulse/PipeWire). Only affects off-path work.
CAPTURE_BLOCK_S = 0.02

# Target lengths: short 2-3 s, medium 8-10 s, long ~30 s at flite's pace.
UTTERANCES: dict[str, str] = {
    "short": "send the updated draft to the review team",
    "medium": (
        "I checked the numbers this morning and the long recordings look fine, "
        "but the short ones still feel slow after I let go of the key, so that is next on the list"
    ),
    "long": (
        "Here is the plan for next week. On Monday we finish the installer changes "
        "and send the build to the test machines. On Tuesday we run the latency "
        "measurement on every laptop we can find and write down the results. "
        "Wednesday is for fixing whatever looks slow, starting with the biggest "
        "number. On Thursday we review the changes together and decide what ships. "
        "Friday is the release, and after that we take a long weekend and do not "
        "look at a single benchmark until Monday. Thanks, everyone."
    ),
}

# A realistic personal vocabulary so post-correction does real work. The
# product default lexicon mode is "native", which skips this stage for
# Parakeet; pass --lexicon-mode native to measure that.
HOTWORDS = (
    "Kubernetes Grafana Prometheus Postgres Tailscale Cloudflare OpenTofu Ansible "
    "Terraform Parakeet Dictate Ubuntu Wayland PipeWire Framework Ryzen Nextcloud "
    "Bitwarden Todoist Obsidian Joplin Inkscape Ghostty Kdenlive Crabbox Xero "
    "Stripe Replit Figma Vikunja"
)
REPLACEMENTS = {"dictate app": "Dictate", "post gres": "Postgres"}


# --------------------------------------------------------------------------- fixtures


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def ensure_fixtures(fixtures_dir: Path, lengths: list[str]) -> dict[str, Path]:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in lengths:
        path = fixtures_dir / f"latency_{name}.wav"
        if not path.is_file():
            if not shutil.which("ffmpeg"):
                raise SystemExit(f"{path} is missing and ffmpeg is not installed to synthesise it")
            text = UTTERANCES[name].replace("'", "").replace(",", "\\,")
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"flite=text='{text}':voice=kal",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "1",
                    "-sample_fmt",
                    "s16",
                    str(path),
                ],
                check=True,
            )
        paths[name] = path
    return paths


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            raise SystemExit(f"{path} must be 16 kHz mono")
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


# --------------------------------------------------------------------------- instruments


@dataclass
class Trace:
    t_release: float = 0.0
    t_stop_done: float = 0.0
    t_decode_start: float = 0.0
    t_decode_end: float = 0.0
    t_history_start: float = 0.0
    t_history_end: float = 0.0
    t_output: float = 0.0
    features_s: float = 0.0
    encoder_s: float = 0.0
    decoder_s: float = 0.0
    decoder_steps: int = 0
    flush_s: float = 0.0
    text: str = ""
    done: threading.Event = field(default_factory=threading.Event)


class ScriptedRecorder:
    """AudioRecorder that replays a prepared utterance instead of a microphone.

    ``prime()`` runs the real capture preprocessor over the utterance in
    callback-sized blocks (that work happens while the user talks). ``stop()``
    does what SoundDeviceRecorder.stop() does after the stream closes: flush the
    preprocessor tail and hand back the buffered audio.
    """

    def __init__(self, harness: Harness) -> None:
        self._h = harness
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._pre = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def truncated(self) -> bool:
        return False

    def start(  # same signature as SoundDeviceRecorder.start
        self,
        on_chunk=None,  # noqa: ANN001
        recording_id: int | None = None,
        note_chunks: bool = False,
        overlap_stream: bool = False,
        on_samples=None,  # noqa: ANN001
    ) -> None:
        del on_chunk, recording_id, note_chunks, overlap_stream, on_samples
        self._recording = True

    def prime(self, audio: np.ndarray) -> float:
        self._pre = create_preprocessor(SAMPLE_RATE)
        block = int(CAPTURE_BLOCK_S * SAMPLE_RATE)
        started = time.perf_counter()
        chunks: list[np.ndarray] = []
        for start in range(0, audio.size, block):
            piece = audio[start : start + block]
            chunks.append(self._pre.process(piece) if self._pre is not None else piece)
        self._chunks = chunks
        return time.perf_counter() - started

    def stop(self) -> np.ndarray:
        trace = self._h.trace
        self._recording = False
        flush_started = time.perf_counter()
        if self._pre is not None:
            tail = self._pre.flush()
            if tail.size:
                self._chunks.append(tail)
            self._pre = None
        audio = (
            np.concatenate(self._chunks).astype(np.float32, copy=False)
            if self._chunks
            else np.array([], np.float32)
        )
        self._chunks = []
        trace.flush_s = time.perf_counter() - flush_started
        trace.t_stop_done = time.perf_counter()
        return audio


class TimedHistoryStore(HistoryStore):
    def __init__(self, path: Path, harness: Harness) -> None:
        super().__init__(path)
        self._h = harness

    def append(self, text: str):  # noqa: ANN201
        self._h.trace.t_history_start = time.perf_counter()
        try:
            return super().append(text)
        finally:
            self._h.trace.t_history_end = time.perf_counter()


class NullOutput:
    name = "null"

    def __init__(self, harness: Harness) -> None:
        self._h = harness

    def send(self, text: str) -> None:
        trace = self._h.trace
        trace.t_output = time.perf_counter()
        trace.text = text
        trace.done.set()


class TimedParakeet(ParakeetSpeechToText):
    """Parakeet backend with timing only. Same signatures, so the engine takes
    the same call path (including its decode_profile TypeError fallback)."""

    harness: Harness | None = None
    sess_options: Any = None

    @property
    def model(self) -> Any:  # same load as the backend unless a thread probe is requested
        if self._model is None and self.sess_options is not None:
            import onnx_asr

            from dictate.stt.parakeet_backend import _MODEL_SPECS, _ensure_model

            spec = _MODEL_SPECS[self.model_name]
            self._model = onnx_asr.load_model(
                spec.onnx_asr_name,
                str(_ensure_model(self.model_name, self.quantization)),
                quantization=self.quantization,
                providers=["CPUExecutionProvider"],
                sess_options=self.sess_options,
            )
        return ParakeetSpeechToText.model.fget(self)  # type: ignore[attr-defined]

    def transcribe_segments(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
        *,
        initial_prompt: str | None = None,
        long_form: bool = False,
    ):  # noqa: ANN201
        trace = self.harness.trace
        trace.t_decode_start = time.perf_counter()
        try:
            return super().transcribe_segments(
                audio,
                language,
                hotwords,
                prompt_context,
                initial_prompt=initial_prompt,
                long_form=long_form,
            )
        finally:
            trace.t_decode_end = time.perf_counter()


def instrument_asr(stt: TimedParakeet, harness: Harness) -> Any:
    """Wrap the onnx-asr model's internal stages on the instance (timing only)."""
    asr = stt.model.asr
    pre, enc, dec_loop, dec_step = asr._preprocessor, asr._encode, asr._decoding, asr._decode

    def timed_pre(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        started = time.perf_counter()
        try:
            return pre(*args, **kwargs)
        finally:
            harness.trace.features_s += time.perf_counter() - started

    def timed_enc(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        started = time.perf_counter()
        try:
            return enc(*args, **kwargs)
        finally:
            harness.trace.encoder_s += time.perf_counter() - started

    def timed_loop(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        started = time.perf_counter()
        try:
            return list(dec_loop(*args, **kwargs))
        finally:
            harness.trace.decoder_s += time.perf_counter() - started

    def counted_step(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        harness.trace.decoder_steps += 1
        return dec_step(*args, **kwargs)

    asr._preprocessor, asr._encode, asr._decoding, asr._decode = (
        timed_pre,
        timed_enc,
        timed_loop,
        counted_step,
    )
    return asr


def onnx_thread_settings(asr: Any) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for label in ("_encoder", "_decoder_joint"):
        session = getattr(asr, label, None)
        if session is None:
            continue
        options = session.get_session_options()
        info[label.strip("_")] = {
            "providers": session.get_providers(),
            "intra_op_num_threads": options.intra_op_num_threads,
            "inter_op_num_threads": options.inter_op_num_threads,
            "execution_mode": str(options.execution_mode),
            "graph_optimization_level": str(options.graph_optimization_level),
        }
    return info


def process_threads() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("Threads:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------- harness


class Harness:
    def __init__(self, args: argparse.Namespace, workdir: Path) -> None:
        self.trace = Trace()
        self.verbose = args.verbose
        self.idle_s = args.idle_s
        self.phase_index = args.phase_index
        self._phase_counts: dict[int, int] = {}
        TimedParakeet.harness = self
        if args.intra_op_threads is not None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = args.intra_op_threads
            TimedParakeet.sess_options = options
        self.stt = TimedParakeet(device="cpu", compute_type="int8")
        threads_before = process_threads()
        started = time.perf_counter()
        _ = self.stt.model  # the daemon preloads the model at startup the same way
        self.model_load_s = time.perf_counter() - started
        self.asr = instrument_asr(self.stt, self)
        self.thread_settings = onnx_thread_settings(self.asr)
        self.thread_settings["process_threads_before_load"] = threads_before
        self.thread_settings["process_threads_after_load"] = process_threads()

        history_path = workdir / "history.json"
        seed = HistoryStore(history_path)
        for index in range(MAX_ENTRIES):
            seed.append(f"seed entry {index} " + UTTERANCES["medium"])
        self.recorder = ScriptedRecorder(self)
        self.daemon = Daemon(
            self.stt,
            output=NullOutput(self),
            hotwords=HOTWORDS if args.lexicon_mode != "native" else None,
            lexicon_mode=args.lexicon_mode,
            lexicon_replacements=REPLACEMENTS if args.lexicon_mode != "native" else None,
            history_store=TimedHistoryStore(history_path, self),
            note_store=NoteStore(workdir / "notes"),
            recorder=self.recorder,
        )
        # Only the transcription worker thread; no hotkey listener (no keyboard access).
        self.daemon._ensure_worker_started()

    def run_once(self, audio: np.ndarray, timeout_s: float = 300.0) -> dict[str, Any]:
        self.trace = Trace()
        trace = self.trace
        # The daemon chats on stderr ("Recording...", "Transcribing 2.6s..."); keep it
        # off the report.
        sink = (
            contextlib.nullcontext() if self.verbose else contextlib.redirect_stderr(io.StringIO())
        )
        with sink:
            if not self.daemon._start_recording("dictation"):
                raise RuntimeError("daemon refused to start a recording")
            capture_pre_s = self.recorder.prime(audio)
            # Stand in for the user still talking: an idle gap, then release at a
            # point spread evenly (golden-ratio sequence, per length) across the
            # worker's 100 ms queue-poll cycle, as real key releases would be.
            k = self.phase_index + self._phase_counts.get(audio.size, 0)
            self._phase_counts[audio.size] = self._phase_counts.get(audio.size, 0) + 1
            time.sleep(self.idle_s + ((0.5 + k * 0.6180339887498949) % 1.0) * 0.1)
            trace.t_release = time.perf_counter()
            self.daemon._on_hotkey_release()
            finished = trace.done.wait(timeout_s)
        if not finished:
            raise RuntimeError("no output within timeout (empty transcript or pipeline error)")
        decode_s = trace.t_decode_end - trace.t_decode_start
        return {
            "audio_s": round(audio.size / SAMPLE_RATE, 3),
            "capture_preprocess_s": capture_pre_s,  # off the release path
            "stop_flush_s": trace.t_stop_done - trace.t_release,
            "handoff_s": trace.t_decode_start - trace.t_stop_done,
            "features_s": trace.features_s,
            "encoder_s": trace.encoder_s,
            "decoder_s": trace.decoder_s,
            "decoder_steps": trace.decoder_steps,
            "decode_other_s": decode_s - trace.features_s - trace.encoder_s - trace.decoder_s,
            "decode_s": decode_s,
            "post_correction_s": trace.t_history_start - trace.t_decode_end,
            "history_s": trace.t_history_end - trace.t_history_start,
            "to_output_s": trace.t_output - trace.t_history_end,
            "release_to_output_s": trace.t_output - trace.t_release,
            "text": trace.text,
        }

    def close(self) -> None:
        self.daemon.shutdown()


# --------------------------------------------------------------------------- reporting

STAGES = (
    "stop_flush_s",
    "handoff_s",
    "features_s",
    "encoder_s",
    "decoder_s",
    "decode_other_s",
    "post_correction_s",
    "history_s",
    "to_output_s",
    "release_to_output_s",
)


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = q * (len(ordered) - 1)
    lo, hi = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def summarise(runs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return {
        stage: {
            "median_ms": round(statistics.median(r[stage] for r in runs) * 1000, 1),
            "p90_ms": round(pct([r[stage] for r in runs], 0.9) * 1000, 1),
        }
        for stage in STAGES
    }


def load_average() -> list[float] | None:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"Host: {report['host']['cpu']} ({report['host']['logical_cpus']} logical, "
        f"affinity {report['host']['affinity_cpus']}), load before {report['load_before']}, "
        f"after {report['load_after']}",
        f"ONNX Runtime {report['onnxruntime']}, threads: {json.dumps(report['thread_settings'])}",
        "",
        "| Length | Run | n | Audio s | Flush | Handoff | Features | Encoder | Decoder | Post | History "
        "| Release to output (median / p90 ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, block in report["results"].items():
        length, kind = key.split("/")
        s = block["summary"]
        cell = lambda name: f"{s[name]['median_ms']:.0f}"  # noqa: E731
        lines.append(
            f"| {length} | {kind} | {block['n']} | {block['audio_s']:.1f} | {cell('stop_flush_s')} "
            f"| {cell('handoff_s')} | {cell('features_s')} | {cell('encoder_s')} | {cell('decoder_s')} "
            f"| {cell('post_correction_s')} | {cell('history_s')} "
            f"| **{s['release_to_output_s']['median_ms']:.0f}** / {s['release_to_output_s']['p90_ms']:.0f} |"
        )
    if report.get("model_load_s"):
        loads = report["model_load_s"]
        lines.append("")
        lines.append(
            f"Model load (startup, not on the release path): median {statistics.median(loads):.2f} s over {len(loads)} loads"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- main


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        help=f"Parakeet v2 int8 dir (default ${PARAKEET_MODEL_PATH_ENV} or {INSTALLED_MODEL})",
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=REPO_ROOT / "benchmark-fixtures" / "latency"
    )
    parser.add_argument("--lengths", default="short,medium,long")
    parser.add_argument(
        "--warm-reps", type=int, default=10, help="warm runs per length (long gets half)"
    )
    parser.add_argument("--cold-reps", type=int, default=3, help="fresh processes per length")
    parser.add_argument(
        "--lexicon-mode", default="post", choices=("native", "prompt", "post", "hybrid")
    )
    parser.add_argument(
        "--pad-silence-s",
        type=float,
        default=0.0,
        help="lever probe: add this much silence before and after each utterance",
    )
    parser.add_argument(
        "--intra-op-threads",
        type=int,
        help="lever probe: ONNX Runtime intra-op threads (default: runtime default, as shipped)",
    )
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument(
        "--idle-s",
        type=float,
        default=0.5,
        help="idle gap before each release (the user still talking)",
    )
    parser.add_argument("--phase-index", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--verbose", action="store_true", help="show the daemon's own stderr chatter"
    )
    parser.add_argument("--cold-child", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def prepare_audio(path: Path, pad_s: float) -> np.ndarray:
    audio = load_wav(path)
    if pad_s > 0:
        pad = np.zeros(int(pad_s * SAMPLE_RATE), dtype=np.float32)
        audio = np.concatenate((pad, audio, pad))
    return audio


def child_cold(args: argparse.Namespace, fixtures: dict[str, Path]) -> None:
    with tempfile.TemporaryDirectory(prefix="dictate-latency-") as tmp:
        harness = Harness(args, Path(tmp))
        try:
            run = harness.run_once(prepare_audio(fixtures[args.cold_child], args.pad_silence_s))
        finally:
            harness.close()
    print("COLD_RESULT " + json.dumps({"run": run, "model_load_s": harness.model_load_s}))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_path = args.model_path or Path(os.environ.get(PARAKEET_MODEL_PATH_ENV) or INSTALLED_MODEL)
    os.environ[PARAKEET_MODEL_PATH_ENV] = str(model_path)
    lengths = [x.strip() for x in args.lengths.split(",") if x.strip()]
    fixtures = ensure_fixtures(args.fixtures_dir, lengths)

    if args.cold_child:
        child_cold(args, fixtures)
        return 0

    import onnxruntime as ort

    report: dict[str, Any] = {
        "host": {
            "cpu": cpu_model(),
            "logical_cpus": os.cpu_count(),
            "affinity_cpus": len(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else None,
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "onnxruntime": ort.__version__,
        "model_path": str(model_path),
        "lexicon_mode": args.lexicon_mode,
        "pad_silence_s": args.pad_silence_s,
        "intra_op_threads_override": args.intra_op_threads,
        "fixtures": {
            name: {"path": str(path), "duration_s": round(_wav_duration(path), 2)}
            for name, path in fixtures.items()
        },
        "load_before": load_average(),
        "results": {},
        "model_load_s": [],
    }
    audio = {name: prepare_audio(path, args.pad_silence_s) for name, path in fixtures.items()}

    # Cold: a fresh process per sample, first dictation right after model load.
    child_argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--fixtures-dir",
        str(args.fixtures_dir),
        "--model-path",
        str(model_path),
        "--lexicon-mode",
        args.lexicon_mode,
        "--pad-silence-s",
        str(args.pad_silence_s),
        "--idle-s",
        str(args.idle_s),
    ]
    if args.intra_op_threads is not None:
        child_argv += ["--intra-op-threads", str(args.intra_op_threads)]
    for name in lengths:
        runs = []
        for rep in range(args.cold_reps):
            out = subprocess.run(
                child_argv + ["--lengths", name, "--cold-child", name, "--phase-index", str(rep)],
                check=True,
                capture_output=True,
                text=True,
            )
            line = next(x for x in out.stdout.splitlines() if x.startswith("COLD_RESULT "))
            payload = json.loads(line.removeprefix("COLD_RESULT "))
            runs.append(payload["run"])
            report["model_load_s"].append(payload["model_load_s"])
        if runs:
            report["results"][f"{name}/cold"] = {
                "n": len(runs),
                "audio_s": runs[0]["audio_s"],
                "summary": summarise(runs),
                "runs": runs,
            }

    # Warm: one process, one throwaway dictation, then round-robin across lengths.
    with tempfile.TemporaryDirectory(prefix="dictate-latency-") as tmp:
        harness = Harness(args, Path(tmp))
        report["thread_settings"] = harness.thread_settings
        report["model_load_s"].append(harness.model_load_s)
        try:
            harness.run_once(audio[lengths[0]])
            warm: dict[str, list[dict[str, Any]]] = {name: [] for name in lengths}
            for rep in range(args.warm_reps):
                for name in lengths:
                    if name == "long" and rep % 2:
                        continue
                    warm[name].append(harness.run_once(audio[name]))
        finally:
            harness.close()
    for name, runs in warm.items():
        report["results"][f"{name}/warm"] = {
            "n": len(runs),
            "audio_s": runs[0]["audio_s"],
            "summary": summarise(runs),
            "runs": runs,
        }
    report["load_after"] = load_average()
    report["transcripts"] = {
        name: report["results"][f"{name}/warm"]["runs"][0]["text"] for name in lengths
    }

    print(markdown(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2))
        print(f"\nFull report: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
