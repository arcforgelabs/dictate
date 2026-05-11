"""
dictate — local voice-to-text for the terminal.

Usage:
    dictate                   Push-to-talk with system tray icon
    dictate --no-tray         Push-to-talk headless (no tray icon)
    dictate --once            One-shot: record until Enter, print to stdout
    dictate --once --copy     One-shot: record until Enter, copy to clipboard
    dictate benchmark ...     Benchmark STT backends on local WAV files
    dictate controls          Open Windows-friendly configuration/history controls
    dictate doctor ...        Diagnose environment/runtime setup
    dictate prepare-model ... Prepare/download a model before activation
    dictate --stt-backend nemo-canary --model nvidia/canary-1b-flash
    dictate --type-backend wtype  Force typing backend for daemon mode
    dictate --model large-v3-turbo  Use a different STT model
    dictate --add-hotword X   Save a hotword for improved recognition
    dictate --list-hotwords   List saved hotwords
"""

import argparse
import os
import sys
import threading
from typing import Sequence

# Disable HF Xet transport by default to avoid observed hangs on large Canary artifacts.
# Users can override by setting HF_HUB_DISABLE_XET=0 before launch.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from dictate.benchmark import run_benchmark
from dictate.config import (
    Config,
    add_hotwords,
    add_lexicon_replacements,
    load_config,
    remove_hotwords,
    remove_lexicon_replacements,
)
from dictate.doctor import run_doctor
from dictate.engine import DictationEngine
from dictate.hotkey import DEFAULT_PUSH_TO_TALK_COMBO, HotkeyParseError, format_hotkey_combo, normalize_push_to_talk_combo
from dictate.lexicon import LEXICON_MODES, LexiconMode, normalize_lexicon_mode
from dictate.model_prepare import run_prepare_model
from dictate.outputs import (
    BackendUnavailableError,
    ClipboardOutput,
    OutputError,
    StdoutOutput,
    detect_session_type,
    resolve_typing_backend,
)
from dictate.stt import (
    ComputeDevice,
    ComputeType,
    NEMO_CANARY_MODELS,
    STT_BACKENDS,
    SpeechToText,
    SttBackend,
    create_speech_to_text,
    resolve_model_name,
)
from dictate.version import RELEASE_VERSION

SAMPLE_RATE = 16000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dictate",
        description="Local voice-to-text for the terminal",
        epilog="Diagnostics: dictate benchmark --help | dictate doctor --help",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {RELEASE_VERSION}",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="One-shot mode: record until Enter, output text, exit",
    )
    parser.add_argument("--copy", action="store_true", help="One-shot: copy to clipboard")
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Headless daemon mode (no system tray icon)",
    )
    parser.add_argument(
        "--type-backend",
        choices=["auto", "xdotool", "wtype", "ydotool", "pynput"],
        default="auto",
        help="Typing backend for daemon mode (default: auto; Windows uses pynput)",
    )
    parser.add_argument(
        "--stt-backend",
        choices=STT_BACKENDS,
        default="faster-whisper",
        help="Speech-to-text backend (default: faster-whisper)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name. "
            "faster-whisper examples: turbo, large-v3-turbo, large-v3. "
            f"nemo-canary examples: {', '.join(NEMO_CANARY_MODELS)}."
        ),
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "auto"],
        default="auto",
        help="Compute device: cpu, cuda, auto",
    )
    parser.add_argument(
        "--compute-type",
        choices=["int8", "float16", "float32"],
        default="int8",
        help="faster-whisper compute type (ignored by nemo-canary)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code (e.g. en). Auto-detect if omitted",
    )
    parser.add_argument(
        "--lexicon-mode",
        choices=LEXICON_MODES,
        default="native",
        help="Lexical adaptation mode: native, prompt, post, hybrid (default: native)",
    )
    parser.add_argument(
        "--push-to-talk-combo",
        default=DEFAULT_PUSH_TO_TALK_COMBO,
        help="Push-to-talk combo for daemon/tray mode (examples: ctrl_r, ctrl_l, ctrl+space)",
    )
    parser.add_argument(
        "--push-to-talk-key",
        default=None,
        help="Deprecated alias for single-key push-to-talk selection",
    )
    parser.add_argument(
        "--hotwords",
        default=None,
        help="Comma-separated words to boost recognition (e.g. 'OpenBao,Vikunja')",
    )
    parser.add_argument(
        "--add-hotword",
        metavar="WORD",
        help="Add word(s) to saved hotwords (comma-separated). Restart dictate to apply.",
    )
    parser.add_argument(
        "--remove-hotword",
        metavar="WORD",
        help="Remove word(s) from saved hotwords (comma-separated).",
    )
    parser.add_argument(
        "--list-hotwords",
        action="store_true",
        help="List saved hotwords and exit.",
    )
    parser.add_argument(
        "--add-lexicon-replacement",
        action="append",
        metavar="WRONG=RIGHT",
        help=(
            "Add lexical post-correction replacement(s), for example "
            "--add-lexicon-replacement kinneri=canary"
        ),
    )
    parser.add_argument(
        "--remove-lexicon-replacement",
        action="append",
        metavar="WRONG",
        help="Remove lexical post-correction replacement(s) by source form.",
    )
    parser.add_argument(
        "--list-lexicon-replacements",
        action="store_true",
        help="List configured lexical post-correction replacements and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    cli_args = list(argv) if argv is not None else sys.argv[1:]
    if cli_args and cli_args[0] == "prepare-model":
        return run_prepare_model(cli_args[1:])
    if cli_args and cli_args[0] == "benchmark":
        return run_benchmark(cli_args[1:])
    if cli_args and cli_args[0] in {"control", "controls"}:
        from dictate.windows_control import run_control_panel

        return run_control_panel()
    if cli_args and cli_args[0] == "doctor":
        return run_doctor(cli_args[1:])

    parser = build_parser()
    args = parser.parse_args(cli_args)

    handled = _handle_hotword_commands(args)
    if handled is not None:
        return handled

    config = load_config()
    stt_backend, model_name = _resolve_startup_stt(args=args, cli_args=cli_args, config=config)
    stt_device, stt_compute_type = _resolve_startup_runtime(
        args=args,
        cli_args=cli_args,
        config=config,
    )
    lexicon_mode = _resolve_startup_lexicon_mode(
        args=args,
        cli_args=cli_args,
        config=config,
    )
    push_to_talk_combo = _resolve_startup_push_to_talk_combo(
        args=args,
        cli_args=cli_args,
        config=config,
    )

    _run_preflight_or_exit(
        require_typing=not args.once,
        require_clipboard=args.once and args.copy,
        typing_backend=args.type_backend,
        push_to_talk_combo=push_to_talk_combo,
        stt_backend=stt_backend,
        stt_model=model_name,
        stt_device=stt_device,
    )

    stt = _load_stt_or_exit(
        stt_backend=stt_backend,
        model_name=model_name,
        device=stt_device,
        compute_type=stt_compute_type,
    )
    language = _resolve_language(stt, args.language)
    hotwords = _resolve_hotwords(
        stt,
        config=config,
        cli_hotwords=args.hotwords,
        lexicon_mode=lexicon_mode,
    )

    if args.once:
        _run_once(
            stt,
            copy_to_clipboard=args.copy,
            language=language,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=config.lexicon_replacements,
        )
        return 0
    if args.no_tray:
        _run_headless(
            stt,
            type_backend=args.type_backend,
            language=language,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=config.lexicon_replacements,
            push_to_talk_combo=push_to_talk_combo,
        )
        return 0
    _run_tray(
        stt,
        type_backend=args.type_backend,
        language=language,
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=config.lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
    )
    return 0


def main_with_logging() -> int:
    if os.environ.get("DICTATE_DISABLE_STARTUP_LOG") == "1":
        return main()
    from dictate.runtime_logging import run_with_startup_logging

    return run_with_startup_logging(main)


def _resolve_startup_stt(
    *,
    args,  # noqa: ANN001
    cli_args: Sequence[str],
    config: Config,
) -> tuple[SttBackend, str]:
    backend_flag = _flag_in_args(cli_args, "--stt-backend")
    model_flag = _flag_in_args(cli_args, "--model")
    if not backend_flag and not model_flag and config.stt_backend in STT_BACKENDS:
        model_name = _resolve_saved_model_name(config.stt_backend, config.stt_model)
        print(
            f"Using saved STT selection: backend='{config.stt_backend}' model='{model_name}'",
            file=sys.stderr,
        )
        return (config.stt_backend, model_name)
    if not backend_flag and not model_flag and config.stt_backend:
        print(
            f"Ignoring invalid saved STT backend '{config.stt_backend}' in config.",
            file=sys.stderr,
        )
    backend: SttBackend = args.stt_backend
    model_name = _resolve_saved_model_name(backend, args.model)
    if not backend_flag and not model_flag and args.model is None:
        print(
            f"Using automatic STT selection: backend='{backend}' model='{model_name}'",
            file=sys.stderr,
        )
    return (backend, model_name)


def _resolve_saved_model_name(backend: SttBackend, configured_model: str | None) -> str:
    if configured_model:
        return resolve_model_name(backend, configured_model)
    return _default_model_for_backend(backend)


def _default_model_for_backend(backend: SttBackend) -> str:
    if backend == "faster-whisper":
        if _cuda_available_for_faster_whisper():
            return "turbo"
        return "base"
    return resolve_model_name(backend, None)


def _cuda_available_for_faster_whisper() -> bool:
    try:
        import ctranslate2
    except Exception:  # noqa: BLE001
        return False
    try:
        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:  # noqa: BLE001
        return False


def _resolve_startup_runtime(
    *,
    args,  # noqa: ANN001
    cli_args: Sequence[str],
    config: Config,
) -> tuple[ComputeDevice, ComputeType]:
    device_flag = _flag_in_args(cli_args, "--device")
    compute_flag = _flag_in_args(cli_args, "--compute-type")

    device: ComputeDevice = args.device
    if not device_flag and config.stt_device in {"cpu", "cuda", "auto"}:
        device = config.stt_device  # type: ignore[assignment]
        print(f"Using saved STT device: {device}", file=sys.stderr)
    elif not device_flag and config.stt_device:
        print(
            f"Ignoring invalid saved STT device '{config.stt_device}' in config.",
            file=sys.stderr,
        )

    compute_type: ComputeType = args.compute_type
    if not compute_flag and config.stt_compute_type in {"int8", "float16", "float32"}:
        compute_type = config.stt_compute_type  # type: ignore[assignment]
        print(f"Using saved STT compute type: {compute_type}", file=sys.stderr)
    elif not compute_flag and config.stt_compute_type:
        print(
            f"Ignoring invalid saved STT compute type '{config.stt_compute_type}' in config.",
            file=sys.stderr,
        )

    return (device, compute_type)


def _resolve_startup_lexicon_mode(
    *,
    args,  # noqa: ANN001
    cli_args: Sequence[str],
    config: Config,
) -> LexiconMode:
    mode_flag = _flag_in_args(cli_args, "--lexicon-mode")
    if not mode_flag and config.lexicon_mode in LEXICON_MODES:
        mode = normalize_lexicon_mode(config.lexicon_mode)
        print(f"Using saved lexicon mode: {mode}", file=sys.stderr)
        return mode
    if not mode_flag and config.lexicon_mode:
        print(
            f"Ignoring invalid saved lexicon mode '{config.lexicon_mode}' in config.",
            file=sys.stderr,
        )
    return normalize_lexicon_mode(args.lexicon_mode)


def _flag_in_args(cli_args: Sequence[str], name: str) -> bool:
    if name in cli_args:
        return True
    return any(arg.startswith(f"{name}=") for arg in cli_args)


def _resolve_startup_push_to_talk_combo(
    *,
    args,  # noqa: ANN001
    cli_args: Sequence[str],
    config: Config,
) -> str:
    combo_flag = _flag_in_args(cli_args, "--push-to-talk-combo")
    legacy_key_flag = _flag_in_args(cli_args, "--push-to-talk-key")

    if combo_flag:
        try:
            combo = normalize_push_to_talk_combo(args.push_to_talk_combo)
        except HotkeyParseError as exc:
            print(f"Invalid --push-to-talk-combo value: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(f"Using CLI push-to-talk combo: {format_hotkey_combo(combo)}", file=sys.stderr)
        return combo
    if legacy_key_flag and args.push_to_talk_key:
        try:
            combo = normalize_push_to_talk_combo(args.push_to_talk_key)
        except HotkeyParseError as exc:
            print(f"Invalid --push-to-talk-key value: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(f"Using CLI push-to-talk combo: {format_hotkey_combo(combo)}", file=sys.stderr)
        return combo
    if config.push_to_talk_combo:
        try:
            combo = normalize_push_to_talk_combo(config.push_to_talk_combo)
        except HotkeyParseError:
            print(
                f"Ignoring invalid saved push-to-talk combo '{config.push_to_talk_combo}' in config.",
                file=sys.stderr,
            )
        else:
            print(f"Using saved push-to-talk combo: {format_hotkey_combo(combo)}", file=sys.stderr)
            return combo
    if config.push_to_talk_key:
        try:
            combo = normalize_push_to_talk_combo(config.push_to_talk_key)
        except HotkeyParseError:
            print(
                f"Ignoring invalid saved push-to-talk key '{config.push_to_talk_key}' in config.",
                file=sys.stderr,
            )
        else:
            print(f"Using saved push-to-talk combo: {format_hotkey_combo(combo)}", file=sys.stderr)
            return combo
    combo = _default_push_to_talk_combo()
    print(f"Using default push-to-talk combo: {format_hotkey_combo(combo)}", file=sys.stderr)
    return combo


def _default_push_to_talk_combo() -> str:
    if detect_session_type() == "wayland":
        return normalize_push_to_talk_combo("ctrl+space")
    return normalize_push_to_talk_combo(DEFAULT_PUSH_TO_TALK_COMBO)


def _run_preflight_or_exit(
    *,
    require_typing: bool,
    require_clipboard: bool,
    typing_backend: str,
    push_to_talk_combo: str,
    stt_backend: SttBackend,
    stt_model: str,
    stt_device: ComputeDevice,
) -> None:
    from dictate.preflight import run_preflight

    report = run_preflight(
        require_typing=require_typing,
        require_clipboard=require_clipboard,
        typing_backend=typing_backend,
        push_to_talk_combo=push_to_talk_combo,
        stt_backend=stt_backend,
        stt_model=stt_model,
        stt_device=stt_device,
    )
    for note in report.notes:
        print(f"Preflight: {note}", file=sys.stderr)
    for warning in report.warnings:
        print(f"Preflight warning: {warning}", file=sys.stderr)
    if report.errors:
        for error in report.errors:
            print(f"Preflight error: {error}", file=sys.stderr)
        raise SystemExit(2)


def _load_stt_or_exit(
    *,
    stt_backend: SttBackend,
    model_name: str,
    device: ComputeDevice,
    compute_type: ComputeType,
) -> SpeechToText:
    stt = create_speech_to_text(
        backend=stt_backend,
        model=model_name,
        device=device,
        compute_type=compute_type,
    )
    print(
        (
            f"Loading STT backend '{stt_backend}' model '{model_name}' "
            f"on '{device}' ({compute_type})..."
        ),
        file=sys.stderr,
    )
    try:
        _ = stt.model
    except Exception as exc:  # noqa: BLE001
        print(
            f"Failed to load backend '{stt_backend}' model '{model_name}': {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    print("Ready.\n", file=sys.stderr)
    return stt


def _resolve_language(stt: SpeechToText, language: str | None) -> str | None:
    if language and not stt.capabilities.supports_language_hint:
        print(
            f"Warning: backend '{stt.backend_name}' ignores --language; auto mode will be used.",
            file=sys.stderr,
        )
        return None
    return language


def _resolve_hotwords(
    stt: SpeechToText,
    *,
    config: Config,
    cli_hotwords: str | None,
    lexicon_mode: LexiconMode,
) -> str | None:
    words = list(config.hotwords)
    if cli_hotwords:
        words.extend(_parse_csv_words(cli_hotwords))
    hotwords_str = " ".join(words) if words else None
    if not hotwords_str:
        return None
    if lexicon_mode == "native" and not stt.capabilities.supports_hotwords:
        print(
            (
                f"Warning: backend '{stt.backend_name}' does not support hotwords; "
                "ignoring configured hotwords."
            ),
            file=sys.stderr,
        )
        return None
    if lexicon_mode in {"native", "hybrid"} and stt.capabilities.supports_hotwords:
        print(f"Hotwords (native decode): {hotwords_str}", file=sys.stderr)
    if lexicon_mode in {"prompt", "hybrid"} and stt.capabilities.supports_prompt_bias:
        print(f"Hotwords (prompt bias): {hotwords_str}", file=sys.stderr)
    if lexicon_mode in {"post", "hybrid"}:
        print(f"Hotwords (post correction): {hotwords_str}", file=sys.stderr)
    if lexicon_mode in {"prompt", "hybrid"} and not stt.capabilities.supports_prompt_bias:
        print(
            (
                f"Warning: backend '{stt.backend_name}' does not support prompt biasing; "
                "prompt lexicon mode will have no effect."
            ),
            file=sys.stderr,
        )
    return hotwords_str


def _parse_csv_words(value: str) -> list[str]:
    return [word.strip() for word in value.split(",") if word.strip()]


def _handle_hotword_commands(args) -> int | None:  # noqa: ANN001
    if args.add_hotword:
        added = add_hotwords(_parse_csv_words(args.add_hotword))
        if added:
            print(f"Added: {', '.join(added)}", file=sys.stderr)
            print("Restart dictate to apply.", file=sys.stderr)
        else:
            print("Already present, nothing to add.", file=sys.stderr)
        return 0

    if args.remove_hotword:
        removed = remove_hotwords(_parse_csv_words(args.remove_hotword))
        if removed:
            print(f"Removed: {', '.join(removed)}", file=sys.stderr)
            print("Restart dictate to apply.", file=sys.stderr)
        else:
            print("Not found, nothing to remove.", file=sys.stderr)
        return 0

    if args.list_hotwords:
        config = load_config()
        if config.hotwords:
            for word in config.hotwords:
                print(word)
        else:
            print("No hotwords configured.", file=sys.stderr)
        return 0

    if args.add_lexicon_replacement:
        replacements: dict[str, str] = {}
        for item in args.add_lexicon_replacement:
            if "=" not in item:
                print(
                    f"Invalid --add-lexicon-replacement value '{item}' (expected WRONG=RIGHT).",
                    file=sys.stderr,
                )
                return 2
            wrong, right = item.split("=", 1)
            wrong_clean = wrong.strip()
            right_clean = right.strip()
            if not wrong_clean or not right_clean:
                print(
                    f"Invalid --add-lexicon-replacement value '{item}' (empty side).",
                    file=sys.stderr,
                )
                return 2
            replacements[wrong_clean] = right_clean
        added = add_lexicon_replacements(replacements)
        if added:
            for wrong, right in added.items():
                print(f"Added replacement: {wrong} -> {right}", file=sys.stderr)
        else:
            print("No replacements added.", file=sys.stderr)
        return 0

    if args.remove_lexicon_replacement:
        removed = remove_lexicon_replacements(args.remove_lexicon_replacement)
        if removed:
            print(f"Removed replacements: {', '.join(removed)}", file=sys.stderr)
        else:
            print("No matching replacements found.", file=sys.stderr)
        return 0

    if args.list_lexicon_replacements:
        config = load_config()
        if config.lexicon_replacements:
            for wrong, right in sorted(config.lexicon_replacements.items()):
                print(f"{wrong} -> {right}")
        else:
            print("No lexicon replacements configured.", file=sys.stderr)
        return 0
    return None


def record_until_enter(recorder):
    """Record from default mic until Enter is pressed."""
    stop = threading.Event()

    def wait_for_enter():
        try:
            input()
        except EOFError:
            pass
        stop.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()

    print("Recording... (press Enter to stop)", file=sys.stderr)
    audio = recorder.record_until(stop.is_set)
    duration = len(audio) / SAMPLE_RATE
    print(f"  {duration:.1f}s captured", file=sys.stderr)
    return audio


def _run_once(
    stt: SpeechToText,
    *,
    copy_to_clipboard: bool,
    language: str | None,
    hotwords: str | None,
    lexicon_mode: LexiconMode,
    lexicon_replacements: dict[str, str] | None,
) -> None:
    from dictate.audio import AudioCaptureError, SoundDeviceRecorder

    recorder = SoundDeviceRecorder(sample_rate=SAMPLE_RATE)
    engine = DictationEngine(
        stt=stt,
        sample_rate=SAMPLE_RATE,
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
    )

    try:
        audio = record_until_enter(recorder)
    except AudioCaptureError as exc:
        print(f"Microphone error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    result = engine.transcribe(audio, language=language)
    if result.status == "empty":
        print("No audio captured", file=sys.stderr)
        raise SystemExit(1)
    if result.status == "too_short":
        print("Too short, skipped", file=sys.stderr)
        raise SystemExit(1)
    if result.status == "no_speech":
        print("No speech detected", file=sys.stderr)
        raise SystemExit(1)
    if result.status == "error":
        print(f"Transcription failed: {result.error}", file=sys.stderr)
        raise SystemExit(1)

    output = ClipboardOutput() if copy_to_clipboard else StdoutOutput()
    try:
        output.send(result.text)
    except OutputError as exc:
        print(f"Output error ({output.name}): {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if copy_to_clipboard:
        print("Copied to clipboard", file=sys.stderr)


def _resolve_typing_output_or_exit(type_backend: str):
    try:
        return resolve_typing_backend(type_backend)
    except BackendUnavailableError as exc:
        print(f"Typing backend error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run_headless(
    stt: SpeechToText,
    *,
    type_backend: str,
    language: str | None,
    hotwords: str | None,
    lexicon_mode: LexiconMode,
    lexicon_replacements: dict[str, str] | None,
    push_to_talk_combo: str,
) -> None:
    from dictate.daemon import Daemon

    output = _resolve_typing_output_or_exit(type_backend)
    Daemon(
        stt,
        output=output,
        language=language,
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
    ).run()


def _run_tray(
    stt: SpeechToText,
    *,
    type_backend: str,
    language: str | None,
    hotwords: str | None,
    lexicon_mode: LexiconMode,
    lexicon_replacements: dict[str, str] | None,
    push_to_talk_combo: str,
) -> None:
    from dictate.daemon import Daemon
    from dictate.tray import TrayIcon

    output = _resolve_typing_output_or_exit(type_backend)
    TrayIcon(
        Daemon(
            stt,
            output=output,
            language=language,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=lexicon_replacements,
            push_to_talk_combo=push_to_talk_combo,
        )
    ).run()


if __name__ == "__main__":
    raise SystemExit(main_with_logging())
