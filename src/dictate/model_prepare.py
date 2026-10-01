"""Subprocess-friendly model preparation command."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from dictate.model_state import mark_model_failed, mark_model_prepared
from dictate.stt import (
    COMPUTE_TYPES,
    STT_BACKENDS,
    SpeechToText,
    add_retired_device_argument,
    create_speech_to_text,
    note_retired_device,
    resolve_model_name,
)


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
    add_retired_device_argument(parser)
    parser.add_argument(
        "--compute-type",
        choices=COMPUTE_TYPES,
        default="int8",
        help="Compute type for backend initialization",
    )
    args = parser.parse_args(list(argv))
    note_retired_device(args.device)

    model_name = resolve_model_name(args.stt_backend, args.model)
    print(
        f"Preparing STT backend '{args.stt_backend}' model '{model_name}' ({args.compute_type})...",
        file=sys.stderr,
    )
    stt: SpeechToText | None = None
    try:
        stt = _create_loaded_stt(
            backend=args.stt_backend,
            model=model_name,
            compute_type=args.compute_type,
        )
    except Exception as exc:  # noqa: BLE001
        mark_model_failed(
            backend=args.stt_backend,
            model=model_name,
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
        compute_type=args.compute_type,
    )
    print("Model preparation complete.", file=sys.stderr)
    return 0


def _create_loaded_stt(
    *,
    backend: str,
    model: str,
    compute_type: str,
) -> SpeechToText:
    stt = create_speech_to_text(
        backend=backend,  # type: ignore[arg-type]
        model=model,
        compute_type=compute_type,  # type: ignore[arg-type]
    )
    try:
        _prepare_backend_resources(stt)
    except Exception:  # noqa: BLE001
        _release_stt(stt)
        raise
    return stt


def _prepare_backend_resources(stt: SpeechToText) -> None:
    prepare_resources = getattr(stt, "prepare_model_resources", None)
    if callable(prepare_resources):
        prepare_resources()
        return
    _ = stt.model


def _release_stt(stt: SpeechToText | None) -> None:
    if stt is None:
        return
    try:
        stt.release()
    except Exception:  # noqa: BLE001
        pass
