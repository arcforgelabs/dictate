"""Time Dictate's real dictation path from WAV files, without a microphone (#156).

Builds the Daemon the app runs, with the Parakeet engine, its worker thread,
recent history (in a temporary folder) and Dictate's paste output with its
clipboard keeper. Only the microphone is replaced: a recorder that runs the
same capture preprocessing over a WAV file on "key press" and hands the audio
back on "key release". Each dictation then logs the same "Dictation timing"
line the app writes to latest.log, and this script prints those lines and a
JSON summary.

Paste targets (--paste):

- ``edit`` (Windows, default there): a hidden EDIT control in this process,
  pasted with WM_PASTE, so no focused window is needed. Clipboard save, write
  and restore are real.
- ``keys``: the real paste keystroke into whatever window has focus.
- ``none``: no output at all, for timing the decode path alone.

The transcript is never printed. Use synthetic speech, e.g. Windows'
System.Speech, as ``scripts/windows-first-run-smoke.ps1`` does.

Usage:
    python scripts/dictation_latency_probe.py short.wav long.wav --runs 3 --json probe.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
import wave
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np

SAMPLE_RATE = 16000
_PREFIX = "Dictation timing: "


class _LogCapture:
    """Stands in for stderr: not a terminal, so dictated text is never echoed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer = ""
        self.timing_lines: list[str] = []
        self.changed = threading.Condition(self._lock)

    def write(self, data: str) -> int:
        with self._lock:
            self._buffer += data.replace("\r", "\n")
            *done, self._buffer = self._buffer.split("\n")
            for line in done:
                line = line.strip()
                if line.startswith(_PREFIX):
                    self.timing_lines.append(line)
                    self.changed.notify_all()
        return len(data)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def wait_for(self, count: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._lock:
            while len(self.timing_lines) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.changed.wait(remaining)
        return True


def read_wav(path: Path) -> np.ndarray:
    from dictate.audio import resample_audio

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise SystemExit(f"{path}: only 16-bit PCM WAV is supported")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return resample_audio(audio, rate, SAMPLE_RATE)


class WavRecorder:
    """The recorder contract the daemon uses, fed from a WAV file.

    ``start`` runs the app's capture preprocessing (gain control, and noise
    suppression where available) over the clip in 100 ms blocks, as the live
    stream would while the user speaks; ``stop`` returns the result.
    """

    def __init__(self) -> None:
        self.is_recording = False
        self.truncated = False
        self.clip = np.zeros(0, dtype=np.float32)
        self.last_processing_seconds: float | None = None
        self._processed = np.zeros(0, dtype=np.float32)

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        del on_chunk, recording_id, kwargs
        from dictate.audio_preprocess import create_preprocessor

        started = time.perf_counter()
        preprocessor = create_preprocessor(SAMPLE_RATE)
        if preprocessor is None:
            processed = self.clip
        else:
            block = SAMPLE_RATE // 10
            parts = [preprocessor.process(self.clip[i : i + block]) for i in range(0, self.clip.size, block)]
            parts.append(preprocessor.flush())
            processed = np.concatenate(parts) if parts else self.clip
        self.last_processing_seconds = time.perf_counter() - started
        self._processed = processed.astype(np.float32, copy=False)
        self.is_recording = True

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return self._processed.copy()


class _NoOutput:
    name = "none"

    def send(self, text: str) -> None:
        del text


def load_stt(model: str, intra_op_threads: int | None):
    from dictate.stt.factory import create_speech_to_text

    stt = create_speech_to_text(backend="parakeet", model=model, compute_type="int8")
    started = time.perf_counter()
    if intra_op_threads is None:
        _ = stt.model
    else:
        # Same load as ParakeetSpeechToText.model, with an explicit thread count.
        import onnx_asr
        import onnxruntime as ort

        from dictate.stt import parakeet_backend as pb

        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_op_threads
        spec = pb._MODEL_SPECS[stt.model_name]
        stt._model = onnx_asr.load_model(
            spec.onnx_asr_name,
            str(pb._ensure_model(stt.model_name, stt.quantization)),
            quantization=stt.quantization,
            providers=list(pb._CPU_PROVIDERS),
            sess_options=options,
        )
    return stt, time.perf_counter() - started


def environment() -> dict[str, object]:
    info: dict[str, object] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "processor": platform.processor(),
    }
    try:
        import onnxruntime as ort

        info["onnxruntime"] = ort.__version__
    except Exception as exc:  # noqa: BLE001
        info["onnxruntime"] = f"unavailable: {type(exc).__name__}"
    try:
        import onnx_asr

        info["onnx_asr"] = getattr(onnx_asr, "__version__", "?")
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("win"):
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        info["priority_class"] = hex(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()))
        try:
            import psutil  # type: ignore[import-not-found]

            info["physical_cores"] = psutil.cpu_count(logical=False)
        except Exception:  # noqa: BLE001
            pass
    return info


def parse_line(line: str) -> dict[str, object]:
    values: dict[str, object] = {}
    for token in line[len(_PREFIX) :].replace("|", " ").split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if value.endswith("ms") and value[:-2].isdigit():
            values[key] = int(value[:-2])
        elif value.endswith("s"):
            try:
                values[key] = float(value[:-1])
            except ValueError:
                values[key] = value
        else:
            values[key] = value
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wavs", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=3, help="dictations per clip (default 3)")
    parser.add_argument("--model", default="parakeet-tdt-0.6b-v2")
    parser.add_argument(
        "--paste",
        choices=["edit", "keys", "none"],
        default="edit" if sys.platform.startswith("win") else "none",
    )
    parser.add_argument(
        "--intra-op-threads",
        type=int,
        default=None,
        help="load the model with this many ONNX Runtime intra-op threads (default: as the app does)",
    )
    parser.add_argument("--label", default="")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    clips = {path.name: read_wav(path) for path in args.wavs}
    print(json.dumps({"environment": environment()}), flush=True)
    stt, load_s = load_stt(args.model, args.intra_op_threads)
    print(f"model loaded in {load_s:.2f} s", flush=True)

    from dictate.clipboard_keeper import default_clipboard_keeper
    from dictate.daemon import Daemon
    from dictate.history import HistoryStore
    from dictate.note_store import NoteStore
    from dictate.outputs import ClipboardOutput, PasteOutput, PynputOutput

    capture = _LogCapture()
    results: list[dict[str, object]] = []
    with ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        if args.paste == "none":
            output: object = _NoOutput()
        else:
            output = PasteOutput(PynputOutput(), ClipboardOutput(), default_clipboard_keeper())
        if args.paste == "edit":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from windows_clipboard_smoke import EditControl

            edit = EditControl()
            stack.callback(edit.close)
            stack.enter_context(patch("dictate.outputs._send_paste_shortcut", side_effect=edit.paste))

        recorder = WavRecorder()
        daemon = Daemon(
            stt,
            output=output,  # type: ignore[arg-type]
            history_store=HistoryStore(path=root / "history.json"),
            note_store=NoteStore(root / "notes"),
            recorder=recorder,
        )
        original_stderr = sys.stderr
        sys.stderr = capture  # type: ignore[assignment]
        stack.callback(setattr, sys, "stderr", original_stderr)
        stack.callback(daemon.shutdown)
        daemon._ensure_worker_started()

        expected = 0
        for run in range(1, args.runs + 1):
            for name, clip in clips.items():
                recorder.clip = clip
                # Let the worker go idle, as it is between real dictations.
                time.sleep(0.5)
                daemon._on_hotkey_press()
                daemon._on_hotkey_release()
                expected += 1
                if not capture.wait_for(expected, timeout=120):
                    print(f"{name} run {run}: no timing line within 120 s", file=original_stderr)
                    return 1
                line = capture.timing_lines[expected - 1]
                print(f"{name} run {run}: {line}", flush=True)
                results.append({"clip": name, "run": run, **parse_line(line)})

    summary: dict[str, dict[str, float]] = {}
    for name in clips:
        rows = [row for row in results if row["clip"] == name]
        later = [row for row in rows if row["run"] != 1] or rows
        summary[name] = {
            key: statistics.median(float(row[key]) for row in later if isinstance(row.get(key), (int, float)))
            for key in ("audio", "release_to_text", "stop", "wait", "decode", "fixes", "history", "paste")
            if any(isinstance(row.get(key), (int, float)) for row in later)
        }
    report = {
        "label": args.label,
        "paste": args.paste,
        "intra_op_threads": args.intra_op_threads,
        "model_load_s": round(load_s, 2),
        "environment": environment(),
        "runs": results,
        "median_excluding_first_run": summary,
    }
    print(json.dumps({"median_excluding_first_run": summary}), flush=True)
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
