"""Subprocess-friendly model preparation command."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from dictate.model_state import mark_model_failed, mark_model_prepared
from dictate.stt import STT_BACKENDS, SpeechToText, create_speech_to_text, resolve_model_name


def run_prepare_model(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare/download an STT model for fast tray switching")
    parser.add_argument(
        "--stt-backend",
        choices=STT_BACKENDS,
        required=True,
        help="Speech-to-text backend to prepare",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (backend default when omitted)",
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "auto"],
        default="auto",
        help="Compute device for model load validation",
    )
    parser.add_argument(
        "--compute-type",
        choices=["int8", "float16", "float32"],
        default="int8",
        help="Compute type for backend initialization",
    )
    args = parser.parse_args(list(argv))

    model_name = resolve_model_name(args.stt_backend, args.model)
    print(
        f"Preparing STT backend '{args.stt_backend}' model '{model_name}' on '{args.device}' ({args.compute_type})...",
        file=sys.stderr,
    )
    stt: SpeechToText | None = None
    try:
        stt = _create_loaded_stt(
            backend=args.stt_backend,  # type: ignore[arg-type]
            model=model_name,
            device=args.device,  # type: ignore[arg-type]
            compute_type=args.compute_type,  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001
        if _should_retry_on_cpu(exc, requested_device=args.device):
            print(
                "Primary prepare load failed on CUDA/auto; retrying on CPU to complete downloads...",
                file=sys.stderr,
            )
            retry_stt: SpeechToText | None = None
            try:
                retry_stt = _create_loaded_stt(
                    backend=args.stt_backend,  # type: ignore[arg-type]
                    model=model_name,
                    device="cpu",  # type: ignore[arg-type]
                    compute_type="int8",  # type: ignore[arg-type]
                )
            except Exception as retry_exc:  # noqa: BLE001
                mark_model_failed(
                    backend=args.stt_backend,
                    model=model_name,
                    device=args.device,
                    compute_type=args.compute_type,
                    error_message=str(retry_exc),
                )
                print(f"Model preparation failed: {retry_exc}", file=sys.stderr)
                return 2
            finally:
                _release_stt(retry_stt)
        else:
            mark_model_failed(
                backend=args.stt_backend,
                model=model_name,
                device=args.device,
                compute_type=args.compute_type,
                error_message=str(exc),
            )
            print(f"Model preparation failed: {exc}", file=sys.stderr)
            return 2
    finally:
        _release_stt(stt)

    mark_model_prepared(
        backend=args.stt_backend,
        model=model_name,
        device=args.device,
        compute_type=args.compute_type,
    )
    print("Model preparation complete.", file=sys.stderr)
    return 0


def _create_loaded_stt(
    *,
    backend: str,
    model: str,
    device: str,
    compute_type: str,
) -> SpeechToText:
    stt = create_speech_to_text(
        backend=backend,  # type: ignore[arg-type]
        model=model,
        device=device,  # type: ignore[arg-type]
        compute_type=compute_type,  # type: ignore[arg-type]
    )
    try:
        _ = stt.model
    except Exception:  # noqa: BLE001
        _release_stt(stt)
        raise
    return stt


def _release_stt(stt: SpeechToText | None) -> None:
    if stt is None:
        return
    try:
        stt.release()
    except Exception:  # noqa: BLE001
        pass


def _should_retry_on_cpu(exc: Exception, *, requested_device: str) -> bool:
    if requested_device not in {"auto", "cuda"}:
        return False
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "cuda-capable device(s) is/are busy or unavailable",
            "cuda is not available",
            "cuda failed",
            "cuda unavailable",
            "cuda out of memory",
            "out of memory",
        )
    )
