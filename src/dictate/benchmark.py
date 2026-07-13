"""STT benchmark CLI helpers."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

try:
    import resource
except Exception:  # noqa: BLE001
    resource = None  # type: ignore[assignment]

from dictate.stt import (
    COMPUTE_DEVICES,
    STT_BACKENDS,
    SttCapabilities,
    TranscriptSegment,
    create_speech_to_text,
    resolve_default_local_model,
    resolve_model_name,
)


@dataclass(slots=True)
class Sample:
    audio_path: Path
    reference: str
    sample_id: str
    reference_segments: list[TranscriptSegment] | None = None


@dataclass(slots=True)
class SampleResult:
    sample: Sample
    hypothesis: str
    latency_s: float
    duration_s: float
    wer: float
    rtf: float
    rtfx: float
    peak_rss_mb: float | None = None
    hypothesis_segments: list[TranscriptSegment] | None = None
    diarization_error_rate: float | None = None
    speaker_confusion_rate: float | None = None
    segment_boundary_mae_s: float | None = None
    segment_boundary_pair_count: int = 0


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
        choices=COMPUTE_DEVICES,
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
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Use the backend's speaker-attribution path when available.",
    )
    parser.add_argument(
        "--require-speaker-attribution",
        action="store_true",
        help="Fail if --diarize is requested but the backend lacks speaker attribution.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Write machine-readable benchmark results to this JSON file.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Optional label stored in JSON output, e.g. workstation-gpu-cuda.",
    )
    parser.add_argument(
        "--fixture-class",
        choices=("synthetic", "curated-human"),
        default="synthetic",
        help=(
            "Classify the benchmark fixture in JSON output. Synthetic fixtures "
            "are smoke evidence only; curated-human fixtures may be used for "
            "promotion gates."
        ),
    )
    parser.add_argument(
        "--fixture-notes",
        default=None,
        help="Optional short fixture provenance note stored in JSON output.",
    )
    parser.add_argument(
        "--validate-manifest-only",
        action="store_true",
        help="Validate manifest/audio metadata and exit without loading an STT model.",
    )
    parser.add_argument(
        "--max-mean-wer",
        type=float,
        default=None,
        help="Fail if summary mean WER exceeds this threshold.",
    )
    parser.add_argument(
        "--max-mean-rtf",
        type=float,
        default=None,
        help="Fail if summary mean real-time factor exceeds this threshold.",
    )
    parser.add_argument(
        "--max-mean-der",
        type=float,
        default=None,
        help="Fail if summary mean diarization error rate exceeds this threshold.",
    )
    parser.add_argument(
        "--max-mean-speaker-confusion-rate",
        type=float,
        default=None,
        help="Fail if summary mean speaker-confusion rate exceeds this threshold.",
    )
    parser.add_argument(
        "--max-mean-segment-boundary-mae-s",
        type=float,
        default=None,
        help="Fail if summary mean segment boundary MAE exceeds this threshold.",
    )
    parser.add_argument(
        "--require-timestamp-metrics",
        action="store_true",
        help="Fail if reference/hypothesis segments do not produce timestamp metrics.",
    )
    parser.add_argument(
        "--require-der-metrics",
        action="store_true",
        help="Fail if reference/hypothesis segments do not produce diarization error metrics.",
    )
    return parser


def run_benchmark(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run_from_args(args)


def _run_from_args(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    audio_root = Path(args.audio_root).expanduser().resolve()
    manifest_issues = validate_manifest_for_benchmark(
        manifest_path,
        audio_root,
        fixture_class=getattr(args, "fixture_class", "synthetic"),
        diarize=bool(args.diarize),
        require_timestamp_metrics=bool(args.require_timestamp_metrics),
        require_der_metrics=bool(args.require_der_metrics),
    )
    if manifest_issues:
        error = "; ".join(manifest_issues)
        for issue in manifest_issues:
            print(f"Manifest validation failed: {issue}", file=sys.stderr)
        if args.json_output:
            write_json_report(
                Path(args.json_output).expanduser().resolve(),
                args=args,
                model_name=args.model or "",
                capabilities=SttCapabilities(),
                results=[],
                summary={
                    "samples": 0,
                    "completed_samples": 0,
                    "error": error,
                },
                gates=[
                    {
                        "name": "manifest_validation",
                        "passed": False,
                        "value": error,
                        "threshold": "valid benchmark manifest",
                    }
                ],
            )
        return 2

    if getattr(args, "validate_manifest_only", False):
        samples = load_manifest(manifest_path, audio_root, limit=args.limit)
        print(f"Manifest validation passed: {len(samples)} sample(s)")
        return 0

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
        try:
            hypothesis, hypothesis_segments = _transcribe_for_benchmark(
                stt,
                audio,
                language=args.language,
                hotwords=hotwords,
                diarize=args.diarize,
                require_speaker_attribution=args.require_speaker_attribution,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{exc.__class__.__name__}: {exc}"
            print(f"[{sample.sample_id}] ERROR {error}")
            gates = [
                {
                    "name": "benchmark_runtime",
                    "passed": False,
                    "value": error,
                    "threshold": "no runtime error",
                }
            ]
            if args.json_output:
                write_json_report(
                    Path(args.json_output).expanduser().resolve(),
                    args=args,
                    model_name=model_name,
                    capabilities=stt.capabilities,
                    results=results,
                    summary={
                        "samples": len(results),
                        "completed_samples": len(results),
                        "failed_sample": sample.sample_id,
                        "error": error,
                    },
                    gates=gates,
                )
            return 2
        latency = time.perf_counter() - start
        duration = len(audio) / 16000.0
        wer = word_error_rate(sample.reference, hypothesis)
        rtf = latency / max(duration, 1e-6)
        rtfx = duration / max(latency, 1e-9)
        speaker_confusion = speaker_confusion_rate(
            sample.reference_segments,
            hypothesis_segments,
        )
        der = diarization_error_rate(
            sample.reference_segments,
            hypothesis_segments,
        )
        boundary_mae, boundary_pairs = segment_boundary_stats_s(
            sample.reference_segments,
            hypothesis_segments,
        )
        results.append(
            SampleResult(
                sample=sample,
                hypothesis=hypothesis,
                latency_s=latency,
                duration_s=duration,
                wer=wer,
                rtf=rtf,
                rtfx=rtfx,
                peak_rss_mb=_peak_rss_mb(),
                hypothesis_segments=hypothesis_segments,
                diarization_error_rate=der,
                speaker_confusion_rate=speaker_confusion,
                segment_boundary_mae_s=boundary_mae,
                segment_boundary_pair_count=boundary_pairs,
            )
        )
        print(
            f"[{sample.sample_id}] dur={duration:.2f}s lat={latency*1000:.1f}ms "
            f"rtf={rtf:.3f} rtfx={rtfx:.2f} wer={wer:.3f}"
            + (_metric_suffix("der", der))
            + (_metric_suffix("speaker_confusion", speaker_confusion))
            + (_metric_suffix("boundary_mae_s", boundary_mae))
        )

    mean_wer = float(np.mean([r.wer for r in results]))
    mean_latency = float(np.mean([r.latency_s for r in results]))
    mean_rtf = float(np.mean([r.rtf for r in results]))
    mean_rtfx = float(np.mean([r.rtfx for r in results]))
    mean_der = _mean_optional([r.diarization_error_rate for r in results])
    mean_speaker_confusion = _mean_optional([r.speaker_confusion_rate for r in results])
    mean_boundary_mae = _mean_optional([r.segment_boundary_mae_s for r in results])
    timestamp_pair_count = int(sum(r.segment_boundary_pair_count for r in results))
    peak_rss = max((r.peak_rss_mb for r in results if r.peak_rss_mb is not None), default=None)
    gates = _evaluate_gates(
        args,
        summary={
            "mean_wer": mean_wer,
            "mean_rtf": mean_rtf,
            "mean_der": mean_der,
            "mean_speaker_confusion_rate": mean_speaker_confusion,
            "mean_segment_boundary_mae_s": mean_boundary_mae,
            "segment_boundary_pair_count": timestamp_pair_count,
        },
    )

    print("\nSummary")
    print(f"  samples: {len(results)}")
    print(f"  mean_wer: {mean_wer:.4f}")
    print(f"  mean_latency_ms: {mean_latency * 1000.0:.2f}")
    print(f"  mean_rtf: {mean_rtf:.4f}")
    print(f"  mean_rtfx: {mean_rtfx:.2f}")
    if mean_der is not None:
        print(f"  mean_der: {mean_der:.4f}")
    if mean_speaker_confusion is not None:
        print(f"  mean_speaker_confusion_rate: {mean_speaker_confusion:.4f}")
    if mean_boundary_mae is not None:
        print(f"  mean_segment_boundary_mae_s: {mean_boundary_mae:.4f}")
    print(f"  segment_boundary_pair_count: {timestamp_pair_count}")
    if peak_rss is not None:
        print(f"  peak_rss_mb: {peak_rss:.1f}")
    if gates:
        print("  gates:")
        for gate in gates:
            print(
                f"    {gate['name']}: "
                f"{'pass' if gate['passed'] else 'FAIL'} "
                f"(value={gate['value']!r}, threshold={gate['threshold']!r})"
            )
    if args.json_output:
        write_json_report(
            Path(args.json_output).expanduser().resolve(),
            args=args,
            model_name=model_name,
            capabilities=stt.capabilities,
            results=results,
            summary={
                "samples": len(results),
                "mean_wer": mean_wer,
                "mean_latency_ms": mean_latency * 1000.0,
                "mean_rtf": mean_rtf,
                "mean_rtfx": mean_rtfx,
                "mean_der": mean_der,
                "mean_speaker_confusion_rate": mean_speaker_confusion,
                "mean_segment_boundary_mae_s": mean_boundary_mae,
                "segment_boundary_pair_count": timestamp_pair_count,
                "peak_rss_mb": peak_rss,
            },
            gates=gates,
        )
    return 0 if all(gate["passed"] for gate in gates) else 2


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
            samples.append(
                Sample(
                    audio_path=audio_path,
                    reference=text,
                    sample_id=sample_id,
                    reference_segments=_load_reference_segments(
                        row,
                        manifest_path.parent,
                        audio_root,
                    ),
                )
            )
            if limit and len(samples) >= limit:
                break
    return samples


def validate_manifest_for_benchmark(
    manifest_path: Path,
    audio_root: Path,
    *,
    fixture_class: str,
    diarize: bool,
    require_timestamp_metrics: bool,
    require_der_metrics: bool,
) -> list[str]:
    issues: list[str] = []
    try:
        samples = load_manifest(manifest_path, audio_root, limit=0)
    except Exception as exc:  # noqa: BLE001
        return [f"could not load manifest: {exc}"]
    if not samples:
        return ["manifest has no usable samples"]

    missing_audio = [sample.sample_id for sample in samples if not sample.audio_path.exists()]
    if missing_audio:
        issues.append("samples missing audio files: " + ", ".join(missing_audio[:5]))

    if fixture_class == "curated-human":
        lower_parts = {part.lower() for part in (*manifest_path.parts, *audio_root.parts)}
        if "benchmark-fixtures" in lower_parts:
            issues.append("curated-human fixtures must not use the generated benchmark-fixtures directory")
        if any("flite" in sample.sample_id.lower() for sample in samples):
            issues.append("curated-human fixtures must not use generated flite sample ids")
        if any("flite" in sample.audio_path.name.lower() for sample in samples):
            issues.append("curated-human fixtures must not use generated flite audio filenames")

    if require_timestamp_metrics:
        missing = [
            sample.sample_id
            for sample in samples
            if not _segments_have_any_timestamps(sample.reference_segments)
        ]
        if missing:
            issues.append("samples missing timestamped reference segments: " + ", ".join(missing[:5]))

    if diarize or require_der_metrics:
        missing = [
            sample.sample_id
            for sample in samples
            if not sample.reference_segments
            or not _segments_have_speaker_timestamps(sample.reference_segments)
        ]
        if missing:
            issues.append(
                "samples missing timestamped speaker reference segments: " + ", ".join(missing[:5])
            )

    return issues


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
    from dictate.audio import resample_audio

    return resample_audio(audio, src_rate, 16000)


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


def _transcribe_for_benchmark(
    stt: Any,
    audio: np.ndarray,
    *,
    language: str | None,
    hotwords: str | None,
    diarize: bool,
    require_speaker_attribution: bool,
) -> tuple[str, list[TranscriptSegment] | None]:
    if not diarize:
        segment_transcriber = _defined_method(stt, "transcribe_segments")
        if segment_transcriber is not None:
            segments = segment_transcriber(audio, language=language, hotwords=hotwords)
            return _segments_to_text(segments), segments
        return stt.transcribe(audio, language=language, hotwords=hotwords).strip(), None
    if require_speaker_attribution and not stt.capabilities.supports_speaker_attribution:
        raise RuntimeError(
            f"Backend '{stt.backend_name}' does not support required speaker attribution."
        )
    segment_transcriber = _defined_method(stt, "transcribe_diarized_segments")
    if segment_transcriber is not None:
        segments = segment_transcriber(audio, language=language, hotwords=hotwords)
        return _segments_to_text(segments), segments
    diarized_transcriber = _defined_method(stt, "transcribe_diarized")
    if diarized_transcriber is not None:
        text = diarized_transcriber(audio, language=language, hotwords=hotwords).strip()
        return text, parse_speaker_labelled_text(text)
    return stt.transcribe(audio, language=language, hotwords=hotwords).strip(), None


def parse_speaker_labelled_text(text: str) -> list[TranscriptSegment] | None:
    segments: list[TranscriptSegment] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        label, content = stripped.split(":", 1)
        label = label.strip()
        content = content.strip()
        if label and content:
            segments.append(TranscriptSegment(text=content, speaker_label=label))
    return segments or None


def _segments_to_text(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    current_speaker: str | None = None
    current_parts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        speaker = segment.speaker_label or segment.speaker_id
        if speaker:
            if current_parts and speaker != current_speaker:
                lines.append(_segment_line(current_speaker, current_parts))
                current_parts = []
            current_speaker = speaker
            current_parts.append(text)
        else:
            if current_parts:
                lines.append(_segment_line(current_speaker, current_parts))
                current_parts = []
                current_speaker = None
            lines.append(text)
    if current_parts:
        lines.append(_segment_line(current_speaker, current_parts))
    return "\n".join(lines).strip()


def _segment_line(speaker: str | None, parts: list[str]) -> str:
    text = " ".join(part.strip() for part in parts if part.strip()).strip()
    return f"{speaker}: {text}" if speaker else text


def _load_reference_segments(
    row: dict[str, str],
    manifest_dir: Path,
    audio_root: Path,
) -> list[TranscriptSegment] | None:
    raw = (row.get("segments_json") or row.get("segments") or "").strip()
    if not raw:
        return None
    data: object
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        path = Path(raw)
        if not path.is_absolute():
            candidate = manifest_dir / path
            path = candidate if candidate.exists() else audio_root / path
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return None
    segments: list[TranscriptSegment] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        segments.append(
            TranscriptSegment(
                text=text.strip(),
                t_start=_optional_float(item.get("t_start", item.get("start"))),
                t_end=_optional_float(item.get("t_end", item.get("end"))),
                speaker_id=_optional_str(item.get("speaker_id")),
                speaker_label=_optional_str(item.get("speaker_label", item.get("speaker"))),
            )
        )
    return segments or None


def speaker_confusion_rate(
    reference: list[TranscriptSegment] | None,
    hypothesis: list[TranscriptSegment] | None,
) -> float | None:
    if not reference or not hypothesis:
        return None
    if not _segments_have_speaker_timestamps(reference) or not _segments_have_speaker_timestamps(
        hypothesis
    ):
        return None

    mapping = _best_hypothesis_speaker_mapping(reference, hypothesis)
    boundaries = _segment_boundaries(reference, hypothesis)
    if len(boundaries) < 2:
        return None

    compared_time = 0.0
    confused_time = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        duration = end - start
        midpoint = start + (duration / 2.0)
        ref_active = _active_speakers_at(reference, midpoint)
        hyp_active = {
            mapping.get(speaker, speaker) for speaker in _active_speakers_at(hypothesis, midpoint)
        }
        if not ref_active or not hyp_active:
            continue
        compared_time += duration
        if ref_active.isdisjoint(hyp_active):
            confused_time += duration
    if compared_time <= 0.0:
        return None
    return confused_time / compared_time


def segment_boundary_mae_s(
    reference: list[TranscriptSegment] | None,
    hypothesis: list[TranscriptSegment] | None,
) -> float | None:
    mae, _count = segment_boundary_stats_s(reference, hypothesis)
    return mae


def diarization_error_rate(
    reference: list[TranscriptSegment] | None,
    hypothesis: list[TranscriptSegment] | None,
) -> float | None:
    """Return a simple timestamped DER with optimal hypothesis speaker mapping."""

    if not reference or not hypothesis:
        return None
    if not _segments_have_speaker_timestamps(reference) or not _segments_have_speaker_timestamps(
        hypothesis
    ):
        return None

    ref_speakers = sorted({_speaker_key(segment) for segment in reference if _speaker_key(segment)})
    hyp_speakers = sorted({_speaker_key(segment) for segment in hypothesis if _speaker_key(segment)})
    if not ref_speakers or not hyp_speakers:
        return None

    mapping = _best_hypothesis_speaker_mapping(reference, hypothesis)
    boundaries = _segment_boundaries(reference, hypothesis)
    if len(boundaries) < 2:
        return None

    ref_speech_time = 0.0
    error_time = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        duration = end - start
        midpoint = start + (duration / 2.0)
        ref_active = _active_speakers_at(reference, midpoint)
        hyp_active = {
            mapping.get(speaker, speaker) for speaker in _active_speakers_at(hypothesis, midpoint)
        }
        if ref_active:
            ref_speech_time += duration
        if not ref_active and hyp_active:
            error_time += duration
        elif ref_active and not hyp_active:
            error_time += duration
        elif ref_active and hyp_active and ref_active.isdisjoint(hyp_active):
            error_time += duration
    if ref_speech_time <= 0.0:
        return None
    return error_time / ref_speech_time


def segment_boundary_stats_s(
    reference: list[TranscriptSegment] | None,
    hypothesis: list[TranscriptSegment] | None,
) -> tuple[float | None, int]:
    if not reference or not hypothesis:
        return None, 0
    if _segments_have_speaker_timestamps(reference) and _segments_have_speaker_timestamps(hypothesis):
        mapping = _best_hypothesis_speaker_mapping(reference, hypothesis)
        errors: list[float] = []
        for ref in reference:
            ref_speaker = _speaker_key(ref)
            if ref_speaker is None or ref.t_start is None or ref.t_end is None:
                continue
            candidates = [
                hyp
                for hyp in hypothesis
                if hyp.t_start is not None
                and hyp.t_end is not None
                and mapping.get(_speaker_key(hyp) or "", _speaker_key(hyp)) == ref_speaker
                and _segment_overlap_s(ref, hyp) > 0.0
            ]
            if not candidates:
                continue
            errors.append(min(abs(ref.t_start - (hyp.t_start or 0.0)) for hyp in candidates))
            errors.append(min(abs(ref.t_end - (hyp.t_end or 0.0)) for hyp in candidates))
        if errors:
            return float(np.mean(errors)), len(errors)
    errors: list[float] = []
    for ref, hyp in zip(reference, hypothesis):
        if ref.t_start is not None and hyp.t_start is not None:
            errors.append(abs(ref.t_start - hyp.t_start))
        if ref.t_end is not None and hyp.t_end is not None:
            errors.append(abs(ref.t_end - hyp.t_end))
    if not errors:
        return None, 0
    return float(np.mean(errors)), len(errors)


def write_json_report(
    path: Path,
    *,
    args: argparse.Namespace,
    model_name: str,
    capabilities: SttCapabilities,
    results: list[SampleResult],
    summary: dict[str, object],
    gates: list[dict[str, object]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "run_label": args.run_label,
        "created_at_unix": time.time(),
        "environment": _environment_payload(),
        "config": {
            "backend": args.stt_backend,
            "model": model_name,
            "device": args.device,
            "language": args.language,
            "diarize": bool(args.diarize),
            "require_speaker_attribution": bool(args.require_speaker_attribution),
            "fixture_class": getattr(args, "fixture_class", "synthetic"),
            "fixture_notes": getattr(args, "fixture_notes", None),
            "capabilities": asdict(capabilities),
        },
        "summary": summary,
        "gates": gates or [],
        "samples": [_sample_result_payload(result) for result in results],
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _sample_result_payload(result: SampleResult) -> dict[str, object]:
    return {
        "id": result.sample.sample_id,
        "audio": str(result.sample.audio_path),
        "duration_s": result.duration_s,
        "latency_s": result.latency_s,
        "rtf": result.rtf,
        "rtfx": result.rtfx,
        "wer": result.wer,
        "peak_rss_mb": result.peak_rss_mb,
        "reference": result.sample.reference,
        "hypothesis": result.hypothesis,
        "diarization_error_rate": result.diarization_error_rate,
        "speaker_confusion_rate": result.speaker_confusion_rate,
        "segment_boundary_mae_s": result.segment_boundary_mae_s,
        "segment_boundary_pair_count": result.segment_boundary_pair_count,
        "reference_segments": _segments_payload(result.sample.reference_segments),
        "hypothesis_segments": _segments_payload(result.hypothesis_segments),
    }


def _environment_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "onnxruntime_providers": _onnxruntime_providers(),
    }
    gpu_summary = _gpu_summary()
    if gpu_summary:
        payload["gpu_summary"] = gpu_summary
    return payload


def _onnxruntime_providers() -> list[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return []


def _gpu_summary() -> list[str]:
    lines: list[str] = []
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        lines.extend(
            _command_lines(
                [
                    nvidia_smi,
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader",
                ]
            )
        )
    lspci = shutil.which("lspci")
    if lspci:
        lines.extend(
            line
            for line in _command_lines([lspci])
            if any(token in line.lower() for token in ("vga", "3d controller", "display"))
        )
    if platform.system().lower() == "windows":
        lines.extend(
            _command_lines(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                ]
            )
        )
    return [line for line in lines if line.strip()]


def _command_lines(command: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _evaluate_gates(
    args: argparse.Namespace,
    *,
    summary: dict[str, object],
) -> list[dict[str, object]]:
    gates: list[dict[str, object]] = []
    _append_max_gate(gates, "mean_wer", summary.get("mean_wer"), getattr(args, "max_mean_wer", None))
    _append_max_gate(gates, "mean_rtf", summary.get("mean_rtf"), getattr(args, "max_mean_rtf", None))
    _append_max_gate(gates, "mean_der", summary.get("mean_der"), getattr(args, "max_mean_der", None))
    _append_max_gate(
        gates,
        "mean_speaker_confusion_rate",
        summary.get("mean_speaker_confusion_rate"),
        getattr(args, "max_mean_speaker_confusion_rate", None),
    )
    _append_max_gate(
        gates,
        "mean_segment_boundary_mae_s",
        summary.get("mean_segment_boundary_mae_s"),
        getattr(args, "max_mean_segment_boundary_mae_s", None),
    )
    if getattr(args, "require_timestamp_metrics", False):
        pair_count = summary.get("segment_boundary_pair_count")
        passed = isinstance(pair_count, int) and pair_count > 0
        gates.append(
            {
                "name": "require_timestamp_metrics",
                "passed": passed,
                "value": pair_count,
                "threshold": ">0",
            }
        )
    if getattr(args, "require_der_metrics", False):
        value = summary.get("mean_der")
        passed = isinstance(value, int | float)
        gates.append(
            {
                "name": "require_der_metrics",
                "passed": passed,
                "value": value,
                "threshold": "present",
            }
        )
    return gates


def _append_max_gate(
    gates: list[dict[str, object]],
    name: str,
    value: object,
    threshold: float | None,
) -> None:
    if threshold is None:
        return
    passed = isinstance(value, int | float) and float(value) <= threshold
    gates.append(
        {
            "name": name,
            "passed": passed,
            "value": value,
            "threshold": threshold,
        }
    )


def _segments_payload(segments: list[TranscriptSegment] | None) -> list[dict[str, object]] | None:
    if segments is None:
        return None
    payload: list[dict[str, object]] = []
    for segment in segments:
        item: dict[str, object] = {"text": segment.text}
        if segment.t_start is not None:
            item["t_start"] = segment.t_start
        if segment.t_end is not None:
            item["t_end"] = segment.t_end
        if segment.speaker_id is not None:
            item["speaker_id"] = segment.speaker_id
        if segment.speaker_label is not None:
            item["speaker_label"] = segment.speaker_label
        payload.append(item)
    return payload


def _defined_method(obj: object, name: str):
    if name not in dir(obj):
        return None
    method = getattr(obj, name, None)
    return method if callable(method) else None


def _speaker_key(segment: TranscriptSegment) -> str | None:
    return segment.speaker_label or segment.speaker_id


def _segments_have_speaker_timestamps(segments: list[TranscriptSegment]) -> bool:
    return all(
        _speaker_key(segment) is not None and segment.t_start is not None and segment.t_end is not None
        for segment in segments
    )


def _segments_have_any_timestamps(segments: list[TranscriptSegment] | None) -> bool:
    return bool(
        segments
        and all(
            segment.t_start is not None
            and segment.t_end is not None
            and segment.t_end > segment.t_start
            for segment in segments
        )
    )


def _segment_boundaries(
    reference: list[TranscriptSegment],
    hypothesis: list[TranscriptSegment],
) -> list[float]:
    boundaries = {
        value
        for segment in [*reference, *hypothesis]
        for value in (segment.t_start, segment.t_end)
        if value is not None
    }
    return sorted(boundaries)


def _active_speakers_at(segments: list[TranscriptSegment], timestamp: float) -> set[str]:
    active: set[str] = set()
    for segment in segments:
        speaker = _speaker_key(segment)
        if speaker is None or segment.t_start is None or segment.t_end is None:
            continue
        if segment.t_start <= timestamp < segment.t_end:
            active.add(speaker)
    return active


def _best_hypothesis_speaker_mapping(
    reference: list[TranscriptSegment],
    hypothesis: list[TranscriptSegment],
) -> dict[str, str]:
    ref_speakers = sorted({_speaker_key(segment) for segment in reference if _speaker_key(segment)})
    hyp_speakers = sorted({_speaker_key(segment) for segment in hypothesis if _speaker_key(segment)})
    overlap: dict[tuple[str, str], float] = {
        (hyp, ref): _speaker_overlap_s(hypothesis, hyp, reference, ref)
        for hyp in hyp_speakers
        for ref in ref_speakers
    }
    remaining_refs = set(ref_speakers)
    mapping: dict[str, str] = {}
    for hyp in sorted(
        hyp_speakers,
        key=lambda speaker: max((overlap[(speaker, ref)] for ref in ref_speakers), default=0.0),
        reverse=True,
    ):
        best_ref = max(
            remaining_refs or set(ref_speakers),
            key=lambda ref: overlap.get((hyp, ref), 0.0),
        )
        if overlap.get((hyp, best_ref), 0.0) > 0:
            mapping[hyp] = best_ref
            remaining_refs.discard(best_ref)
        else:
            mapping[hyp] = hyp
    return mapping


def _speaker_overlap_s(
    left_segments: list[TranscriptSegment],
    left_speaker: str,
    right_segments: list[TranscriptSegment],
    right_speaker: str,
) -> float:
    total = 0.0
    for left in left_segments:
        if _speaker_key(left) != left_speaker or left.t_start is None or left.t_end is None:
            continue
        for right in right_segments:
            if _speaker_key(right) != right_speaker or right.t_start is None or right.t_end is None:
                continue
            total += max(0.0, min(left.t_end, right.t_end) - max(left.t_start, right.t_start))
    return total


def _segment_overlap_s(left: TranscriptSegment, right: TranscriptSegment) -> float:
    if (
        left.t_start is None
        or left.t_end is None
        or right.t_start is None
        or right.t_end is None
    ):
        return 0.0
    return max(0.0, min(left.t_end, right.t_end) - max(left.t_start, right.t_start))


def _optional_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _peak_rss_mb() -> float | None:
    if resource is None:
        return None
    try:
        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # noqa: BLE001
        return None
    if sys.platform == "darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


def _mean_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return float(np.mean(present)) if present else None


def _metric_suffix(name: str, value: float | None) -> str:
    return f" {name}={value:.3f}" if value is not None else ""
