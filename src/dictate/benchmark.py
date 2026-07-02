"""STT benchmark CLI helpers."""

from __future__ import annotations

import argparse
import csv
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from dictate.stt import (
    STT_BACKENDS,
    create_speech_to_text,
    resolve_default_local_model,
    resolve_model_name,
)


@dataclass(slots=True)
class Sample:
    audio_path: Path
    reference: str
    sample_id: str


@dataclass(slots=True)
class SampleResult:
    sample: Sample
    hypothesis: str
    latency_s: float
    duration_s: float
    wer: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark dictate STT backends")
    parser.add_argument(
        "--manifest",
        required=True,
        help="CSV with columns: audio,text[,id]",
    )
    parser.add_argument(
        "--audio-root",
        default=".",
        help="Base directory used to resolve relative audio paths (default: .)",
    )
    parser.add_argument(
        "--stt-backend",
        choices=STT_BACKENDS,
        default="faster-whisper",
        help="STT backend to evaluate",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (default backend model if omitted)",
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "auto"],
        default="auto",
        help="Compute device",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Language hint passed to backend (default: en)",
    )
    parser.add_argument(
        "--hotwords",
        default=None,
        help="Optional whitespace-separated hotwords (used only on backends that support it)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Evaluate only first N samples")
    return parser


def run_benchmark(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run_from_args(args)


def _run_from_args(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    audio_root = Path(args.audio_root).expanduser().resolve()

    if args.stt_backend == "faster-whisper" and not args.model:
        model_name = resolve_default_local_model(args.device)
    else:
        model_name = resolve_model_name(args.stt_backend, args.model)
    stt = create_speech_to_text(
        backend=args.stt_backend,
        model=model_name,
        device=args.device,
    )

    print(f"Loading backend={args.stt_backend} model={model_name} device={args.device}")
    _ = stt.model

    samples = load_manifest(manifest_path, audio_root, limit=args.limit)
    if not samples:
        print("No samples found.")
        return 1

    if args.hotwords and not stt.capabilities.supports_hotwords:
        print(f"Warning: backend '{stt.backend_name}' ignores hotwords.")
        hotwords = None
    else:
        hotwords = args.hotwords

    results: list[SampleResult] = []
    for sample in samples:
        audio = read_wav_mono_16k(sample.audio_path)
        start = time.perf_counter()
        hypothesis = stt.transcribe(audio, language=args.language, hotwords=hotwords).strip()
        latency = time.perf_counter() - start
        duration = len(audio) / 16000.0
        wer = word_error_rate(sample.reference, hypothesis)
        results.append(
            SampleResult(
                sample=sample,
                hypothesis=hypothesis,
                latency_s=latency,
                duration_s=duration,
                wer=wer,
            )
        )
        print(
            f"[{sample.sample_id}] dur={duration:.2f}s lat={latency*1000:.1f}ms "
            f"rtf={latency/max(duration, 1e-6):.3f} wer={wer:.3f}"
        )

    mean_wer = float(np.mean([r.wer for r in results]))
    mean_latency = float(np.mean([r.latency_s for r in results]))
    mean_rtf = float(np.mean([r.latency_s / max(r.duration_s, 1e-6) for r in results]))

    print("\nSummary")
    print(f"  samples: {len(results)}")
    print(f"  mean_wer: {mean_wer:.4f}")
    print(f"  mean_latency_ms: {mean_latency * 1000.0:.2f}")
    print(f"  mean_rtf: {mean_rtf:.4f}")
    return 0


def load_manifest(manifest_path: Path, audio_root: Path, limit: int) -> list[Sample]:
    samples: list[Sample] = []
    with manifest_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Manifest is missing headers")
        if "audio" not in reader.fieldnames or "text" not in reader.fieldnames:
            raise ValueError("Manifest must include 'audio' and 'text' columns")

        for index, row in enumerate(reader):
            audio = (row.get("audio") or "").strip()
            text = (row.get("text") or "").strip()
            if not audio or not text:
                continue
            sample_id = (row.get("id") or str(index + 1)).strip()
            audio_path = Path(audio)
            if not audio_path.is_absolute():
                audio_path = audio_root / audio_path
            samples.append(Sample(audio_path=audio_path, reference=text, sample_id=sample_id))
            if limit and len(samples) >= limit:
                break
    return samples


def read_wav_mono_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm_bytes = wav_file.readframes(frame_count)

    if sample_width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM WAV, got sample width={sample_width}")

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if sample_rate != 16000:
        audio = _resample_to_16k(audio, sample_rate)
    return audio.astype(np.float32, copy=False)


def _resample_to_16k(audio: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate <= 0:
        raise ValueError(f"Invalid source sample rate: {src_rate}")
    if audio.size == 0:
        return audio

    src_duration = audio.size / float(src_rate)
    target_size = max(1, int(round(src_duration * 16000)))
    src_x = np.linspace(0.0, src_duration, num=audio.size, endpoint=False)
    tgt_x = np.linspace(0.0, src_duration, num=target_size, endpoint=False)
    return np.interp(tgt_x, src_x, audio).astype(np.float32, copy=False)


def normalize_text(text: str) -> list[str]:
    return " ".join(text.lower().strip().split()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    dp = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=np.int32)
    dp[:, 0] = np.arange(len(ref) + 1)
    dp[0, :] = np.arange(len(hyp) + 1)

    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            substitution = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i, j] = min(
                dp[i - 1, j] + 1,
                dp[i, j - 1] + 1,
                dp[i - 1, j - 1] + substitution,
            )
    return float(dp[len(ref), len(hyp)]) / float(len(ref))
