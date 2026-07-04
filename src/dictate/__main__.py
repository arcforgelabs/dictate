"""
dictate — desktop dictation for the focused app.

Usage:
    dictate                   Push-to-talk with system tray icon
    dictate --no-tray         Push-to-talk headless (no tray icon)
    dictate --once            One-shot: record until Enter, print to stdout
    dictate --once --copy     One-shot: record until Enter, copy to clipboard
    dictate benchmark ...     Benchmark STT backends on local WAV files
    dictate controls          Open Windows-friendly configuration/history controls
    dictate doctor ...        Diagnose environment/runtime setup
    dictate prepare-model ... Prepare/download a model before activation
    dictate --stt-backend faster-whisper
    dictate --type-backend wtype  Force typing backend for daemon mode
    dictate --model large-v3-turbo  Use a different STT model
    dictate --add-hotword X   Save a hotword for improved recognition
    dictate --list-hotwords   List saved hotwords
"""

import argparse
import logging
import os
import signal
import sys
import threading
from types import FrameType
from typing import Sequence

# Disable HF Xet transport by default to avoid observed hangs on large model artifacts.
# Users can override by setting HF_HUB_DISABLE_XET=0 before launch.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from dictate.benchmark import run_benchmark
from dictate.config import (
    Config,
    add_hotwords,
    add_lexicon_replacements,
    load_config,
    parse_hotwords_text,
    remove_hotwords,
    remove_lexicon_replacements,
    set_stt_backend,
    set_stt_selection,
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
    resolve_typing_backend,
)
from dictate.process_lock import ProcessLock, daemon_lock_path
from dictate.stt import (
    ComputeDevice,
    ComputeType,
    GEMINI_MODELS,
    OPENAI_MODELS,
    STT_BACKENDS,
    WHISPERX_MODELS,
    SpeechToText,
    SttBackend,
    XAI_MODELS,
    create_speech_to_text,
    resolve_default_local_backend,
    resolve_default_local_model,
    resolve_model_name,
)
from dictate.version import RELEASE_VERSION

SAMPLE_RATE = 16000
_DAEMON_LOCK: ProcessLock | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dictate",
        description="Desktop dictation that types into the focused app",
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
            "local example: turbo. "
            f"whisperx examples: {', '.join(WHISPERX_MODELS)}. "
            f"openai examples: {', '.join(OPENAI_MODELS)}. "
            f"xai examples: {', '.join(XAI_MODELS)}. "
            f"gemini examples: {', '.join(GEMINI_MODELS)}."
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
        help="faster-whisper compute type (ignored by hosted API backends)",
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
        help="Push-to-talk combo for daemon/tray mode (examples: ctrl+d, ctrl_r, ctrl+space)",
    )
    parser.add_argument(
        "--push-to-talk-key",
        default=None,
        help="Deprecated alias for single-key push-to-talk selection",
    )
    parser.add_argument(
        "--hotwords",
        default=None,
        help="Comma-separated words to boost recognition (e.g. 'AcmeWidget,ProjectNova')",
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
            "--add-lexicon-replacement acme-widgit=AcmeWidget"
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
    if cli_args and cli_args[0] == "stop":
        return _handle_stop_command(cli_args[1:])
    if cli_args and cli_args[0] == "doctor":
        return run_doctor(cli_args[1:])
    if cli_args and cli_args[0] == "config":
        return _handle_config_commands(cli_args[1:])

    parser = build_parser()
    args = parser.parse_args(cli_args)

    handled = _handle_hotword_commands(args)
    if handled is not None:
        return handled

    config = load_config()
    stt_backend, model_name = _resolve_startup_stt(args=args, cli_args=cli_args, config=config)
    _apply_configured_secret_commands(config=config, stt_backend=stt_backend)
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

    if args.once:
        _run_preflight_or_exit(
            require_typing=False,
            require_clipboard=args.copy,
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
        _run_once(
            stt,
            copy_to_clipboard=args.copy,
            language=language,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=config.lexicon_replacements,
        )
        return 0

    _acquire_daemon_lock_or_exit()
    try:
        _ensure_desktop_integration()
        _run_preflight_or_exit(
            require_typing=True,
            require_clipboard=False,
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
        if args.no_tray:
            _run_headless(
                stt,
                type_backend=args.type_backend,
                language=language,
                hotwords=hotwords,
                lexicon_mode=lexicon_mode,
                lexicon_replacements=config.lexicon_replacements,
                push_to_talk_combo=push_to_talk_combo,
                stt_backend=stt_backend,
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
            stt_backend=stt_backend,
        )
        return 0
    finally:
        _release_daemon_lock()


def _handle_stop_command(argv: Sequence[str]) -> int:
    """`dictate stop` — stop a running Dictate engine daemon (used on update)."""
    from dictate.process_lock import stop_running_daemon

    quiet = "--quiet" in argv
    stopped, message = stop_running_daemon()
    if not quiet:
        print(message, file=sys.stderr)
    return 0 if stopped else 1


def _ensure_desktop_integration() -> None:
    try:
        from dictate import startup as startup_mod

        startup_mod.ensure_desktop_integration_once()
    except Exception:  # noqa: BLE001
        pass


def _acquire_daemon_lock_or_exit() -> None:
    global _DAEMON_LOCK
    lock = ProcessLock(daemon_lock_path())
    if not lock.acquire():
        print(
            "Dictate is already running. Stop the existing Dictate process before starting another listener.",
            file=sys.stderr,
        )
        raise SystemExit(0)
    _DAEMON_LOCK = lock


def _release_daemon_lock() -> None:
    global _DAEMON_LOCK
    if _DAEMON_LOCK is None:
        return
    try:
        _DAEMON_LOCK.release()
    finally:
        _DAEMON_LOCK = None


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
    device = _startup_device(args=args, cli_args=cli_args, config=config)
    if not backend_flag and not model_flag and config.stt_backend in STT_BACKENDS:
        model_name = _resolve_saved_model_name(config.stt_backend, config.stt_model, device)
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
    # No saved/flagged selection: pick the hardware-aware default local backend
    # (Parakeet English on CPU, Whisper turbo on GPU) rather than the argparse default.
    if not backend_flag and not model_flag:
        backend, model_name = resolve_default_local_backend(device)
        print(
            f"Using automatic STT selection: backend='{backend}' model='{model_name}'",
            file=sys.stderr,
        )
        return (backend, model_name)
    backend: SttBackend = args.stt_backend
    if model_flag:
        model_name = resolve_model_name(backend, args.model)
    else:
        model_name = _resolve_saved_model_name(backend, args.model, device)
    return (backend, model_name)


def _apply_configured_secret_commands(*, config: Config, stt_backend: SttBackend) -> None:
    if stt_backend == "openai" and config.openai_api_key_command:
        os.environ.setdefault("DICTATE_OPENAI_API_KEY_COMMAND", config.openai_api_key_command)
    if stt_backend == "xai" and config.xai_api_key_command:
        os.environ.setdefault("DICTATE_XAI_API_KEY_COMMAND", config.xai_api_key_command)
    if stt_backend == "gemini" and config.gemini_api_key_command:
        os.environ.setdefault("DICTATE_GEMINI_API_KEY_COMMAND", config.gemini_api_key_command)


def _resolve_saved_model_name(
    backend: SttBackend,
    configured_model: str | None,
    device: ComputeDevice = "auto",
) -> str:
    if configured_model:
        return resolve_model_name(backend, configured_model)
    return _default_model_for_backend(backend, device)


def _default_model_for_backend(backend: SttBackend, device: ComputeDevice = "auto") -> str:
    if backend == "faster-whisper":
        return resolve_default_local_model(device)
    return resolve_model_name(backend, None)


def _startup_device(
    *,
    args,  # noqa: ANN001
    cli_args: Sequence[str],
    config: Config,
) -> ComputeDevice:
    """Resolve the effective compute device (no printing) for default-model gating.

    Mirrors the device-selection half of ``_resolve_startup_runtime`` so the local
    default model can be chosen with the same device the daemon will actually use.
    """
    device_flag = _flag_in_args(cli_args, "--device")
    if not device_flag and config.stt_device in {"cpu", "cuda", "auto"}:
        return config.stt_device  # type: ignore[return-value]
    return args.device


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
        try:
            stt.release()
        except Exception as release_exc:  # noqa: BLE001
            print(f"Failed to release STT resources: {release_exc}", file=sys.stderr)
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
    separator = "\n" if stt.backend_name == "xai" else " "
    hotwords_str = separator.join(words) if words else None
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
    return parse_hotwords_text(value)


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


def _config_load_ui_prefs() -> dict:
    """Read ui-prefs.json merged over defaults (the engine's UI-only prefs)."""
    import json

    from dictate.ui_server import DEFAULT_PREFS, UI_PREFS_PATH

    prefs = dict(DEFAULT_PREFS)
    try:
        stored = json.loads(UI_PREFS_PATH.read_text())
        if isinstance(stored, dict):
            prefs.update({k: v for k, v in stored.items() if k in DEFAULT_PREFS})
    except (OSError, ValueError):
        pass
    return prefs


def _config_set_ui_pref(key: str, value: object) -> None:
    """Persist a single ui-prefs.json key (theme, trayOnly, overlay, sound)."""
    import json

    from dictate.ui_server import UI_PREFS_PATH

    prefs = _config_load_ui_prefs()
    prefs[key] = value
    UI_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_PREFS_PATH.write_text(json.dumps(prefs, indent=2))


def _handle_config_commands(argv: list[str]) -> int:  # noqa: C901
    """Handle `dictate config <subcommand>` — keys, provider, and all daily settings.

    This CLI is the single advanced-config surface: the GUI is do-it-for-them and
    exposes no settings, so every user-changeable setting must be reachable here.
    """
    import argparse as _ap

    from dictate.api_keys import (
        API_BACKENDS,
        has_stored_api_key,
        save_api_key,
        secret_store_available,
        secret_store_description,
        validate_api_key_format,
    )

    parser = _ap.ArgumentParser(
        prog="dictate config",
        description="Manage Dictate configuration and API keys",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="cmd")

    # set-key <backend> <KEY>
    sk = sub.add_parser("set-key", help="Save an API key to the OS secret store")
    sk.add_argument(
        "backend",
        choices=list(API_BACKENDS),
        help="API backend (openai, xai, gemini)",
    )
    sk.add_argument("key", help="The API key value")

    # set-provider online|private
    sp = sub.add_parser(
        "set-provider",
        help="Switch between private (on-device faster-whisper) and online (xAI)",
    )
    sp.add_argument(
        "mode",
        choices=["private", "online"],
        help="'private' → faster-whisper; 'online' → xai",
    )

    # set-model <id>
    sm = sub.add_parser("set-model", help="Set the model for the current backend")
    sm.add_argument("model_id", help="Model name (e.g. grok-speech-to-text)")

    # set-shortcut <combo>
    ss = sub.add_parser("set-shortcut", help="Set the push-to-talk shortcut (e.g. ctrl+d)")
    ss.add_argument("combo", help="Key combo, e.g. 'ctrl+d' or 'ctrl+space'")

    # hotwords [--add] [--remove] [--clear]
    hw = sub.add_parser("hotwords", help="List or edit hotwords (terms to always spell correctly)")
    hw.add_argument("--add", help="Comma-separated words to add")
    hw.add_argument("--remove", help="Comma-separated words to remove")
    hw.add_argument("--clear", action="store_true", help="Remove all hotwords")

    # set-theme light|dark|system
    st = sub.add_parser("set-theme", help="Set the appearance theme")
    st.add_argument("value", choices=["light", "dark", "system"])

    # set-startup on|off
    sst = sub.add_parser("set-startup", help="Launch Dictate on sign-in")
    sst.add_argument("mode", choices=["on", "off"])

    # set-behavior <tray|overlay|sound> on|off
    sbe = sub.add_parser("set-behavior", help="Toggle tray-only / listening overlay / sound cue")
    sbe.add_argument("name", choices=["tray", "overlay", "sound"])
    sbe.add_argument("mode", choices=["on", "off"])

    # show
    sub.add_parser("show", help="Print current config and key status")

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 2

    # ---- set-key -----------------------------------------------------------
    if args.cmd == "set-key":
        fmt_error = validate_api_key_format(args.backend, args.key)
        if fmt_error:
            print(f"error: {fmt_error}", file=sys.stderr)
            return 1
        try:
            save_api_key(args.backend, args.key)
        except Exception as exc:  # noqa: BLE001
            print(f"error: could not save key: {exc}", file=sys.stderr)
            return 1
        print(f"ok: {args.backend} key saved to {secret_store_description()}")
        return 0

    # ---- set-provider ------------------------------------------------------
    if args.cmd == "set-provider":
        backend = "faster-whisper" if args.mode == "private" else "xai"
        set_stt_backend(backend)
        print(f"ok: provider={args.mode} (stt_backend={backend})")
        return 0

    # ---- set-model ---------------------------------------------------------
    if args.cmd == "set-model":
        cfg = load_config()
        backend = cfg.stt_backend or "faster-whisper"
        set_stt_selection(backend, args.model_id)
        print(f"ok: model={args.model_id} (backend={backend})")
        return 0

    # ---- set-shortcut ------------------------------------------------------
    if args.cmd == "set-shortcut":
        from dictate.config import set_push_to_talk_combo
        from dictate.hotkey import (
            HotkeyParseError,
            format_hotkey_combo,
            normalize_push_to_talk_combo,
        )

        try:
            combo = normalize_push_to_talk_combo(args.combo)
        except HotkeyParseError as exc:
            print(f"error: invalid shortcut: {exc}", file=sys.stderr)
            return 1
        set_push_to_talk_combo(combo)
        print(f"ok: shortcut={format_hotkey_combo(combo)} ({combo})")
        return 0

    # ---- hotwords ----------------------------------------------------------
    if args.cmd == "hotwords":
        if args.clear:
            current = load_config().hotwords
            if current:
                remove_hotwords(current)
            print("ok: hotwords cleared")
            return 0
        changed = False
        if args.add:
            add_hotwords(_parse_csv_words(args.add))
            changed = True
        if args.remove:
            remove_hotwords(_parse_csv_words(args.remove))
            changed = True
        words = load_config().hotwords
        if changed:
            print(f"ok: hotwords={', '.join(words) if words else '(none)'}")
        elif words:
            for w in words:
                print(w)
        else:
            print("(no hotwords)")
        return 0

    # ---- set-theme ---------------------------------------------------------
    if args.cmd == "set-theme":
        _config_set_ui_pref("theme", args.value)
        print(f"ok: theme={args.value}")
        return 0

    # ---- set-startup -------------------------------------------------------
    if args.cmd == "set-startup":
        from dictate import startup as startup_mod

        enabled = args.mode == "on"
        try:
            startup_mod.set_startup_enabled(enabled)
        except Exception as exc:  # noqa: BLE001
            print(f"error: could not change startup: {exc}", file=sys.stderr)
            return 1
        print(f"ok: startup={'on' if enabled else 'off'}")
        return 0

    # ---- set-behavior ------------------------------------------------------
    if args.cmd == "set-behavior":
        pref_key = {"tray": "trayOnly", "overlay": "overlay", "sound": "sound"}[args.name]
        _config_set_ui_pref(pref_key, args.mode == "on")
        print(f"ok: {args.name}={args.mode}")
        return 0

    # ---- show --------------------------------------------------------------
    if args.cmd == "show":
        cfg = load_config()
        backend = cfg.stt_backend or "faster-whisper"
        mode = "private" if backend == "faster-whisper" else "online"
        model = cfg.stt_model or "(default)"
        prefs = _config_load_ui_prefs()
        print(f"provider: {mode} (stt_backend={backend})")
        print(f"model: {model}")
        print(f"shortcut: {cfg.push_to_talk_combo or DEFAULT_PUSH_TO_TALK_COMBO}")
        hw = cfg.hotwords
        print(f"hotwords: {len(hw)}" + (f" ({', '.join(hw)})" if hw else ""))
        print(f"theme: {prefs.get('theme')}")
        print(f"tray-only: {'on' if prefs.get('trayOnly') else 'off'}")
        print(f"overlay: {'on' if prefs.get('overlay') else 'off'}")
        print(f"sound: {'on' if prefs.get('sound') else 'off'}")
        try:
            from dictate import startup as startup_mod

            startup_on = startup_mod.startup_enabled()
        except Exception:  # noqa: BLE001
            startup_on = False
        print(f"startup: {'on' if startup_on else 'off'}")
        for b in API_BACKENDS:
            has_key = has_stored_api_key(b)
            print(f"key.{b}: {'set' if has_key else 'not-set'}")
        store = secret_store_description()
        available = secret_store_available()
        print(f"secret-store: {store} ({'available' if available else 'unavailable'})")
        return 0

    return 2  # unreachable, argparse catches unknown subcommands


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

    engine: DictationEngine | None = None
    try:
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
        if result.notice:
            print(result.notice, file=sys.stderr)
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
    finally:
        try:
            if engine is not None:
                engine.release()
            else:
                stt.release()
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to release STT resources: {exc}", file=sys.stderr)


def _resolve_typing_output_or_exit(type_backend: str):
    try:
        return resolve_typing_backend(type_backend)
    except BackendUnavailableError as exc:
        print(f"Typing backend error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


class _DaemonSignalHandlers:
    def __init__(self, daemon: object) -> None:
        self._daemon = daemon
        self._previous: dict[signal.Signals, object] = {}

    def __enter__(self) -> "_DaemonSignalHandlers":
        if threading.current_thread() is not threading.main_thread():
            return self
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handle_signal)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if threading.current_thread() is not threading.main_thread():
            return
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        try:
            self._daemon.shutdown()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            print(f"\nShutdown after signal {signum} failed: {exc}", file=sys.stderr)


def _run_headless(
    stt: SpeechToText,
    *,
    type_backend: str,
    language: str | None,
    hotwords: str | None,
    lexicon_mode: LexiconMode,
    lexicon_replacements: dict[str, str] | None,
    push_to_talk_combo: str,
    stt_backend: str,
) -> None:
    from dictate.daemon import Daemon
    from dictate.provider_supervisor import ProviderSupervisor, make_remote_probe

    supervisor = ProviderSupervisor(preferred=stt_backend, probe_fn=make_remote_probe(stt_backend))
    output = _resolve_typing_output_or_exit(type_backend)
    daemon = Daemon(
        stt,
        output=output,
        language=language,
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
        supervisor=supervisor,
    )
    _maybe_start_ui_server(daemon)
    try:
        with _DaemonSignalHandlers(daemon):
            daemon.run()
    finally:
        supervisor.shutdown()


def _maybe_start_ui_server(daemon: object) -> object | None:
    """Start the control server alongside the headless daemon when requested.

    Opt-in via ``DICTATE_UI_SERVER`` so default headless behaviour is unchanged.
    The packaged desktop app sets it so one engine process both dictates and
    serves the Settings window's control API.
    """
    if not os.environ.get("DICTATE_UI_SERVER"):
        return None
    try:
        from dictate import ui_launcher

        return ui_launcher.ensure_server_started(daemon)
    except Exception:  # noqa: BLE001 — never let the control surface block dictation
        logging.getLogger(__name__).exception("Failed to start the UI control server")
        return None


def _run_tray(
    stt: SpeechToText,
    *,
    type_backend: str,
    language: str | None,
    hotwords: str | None,
    lexicon_mode: LexiconMode,
    lexicon_replacements: dict[str, str] | None,
    push_to_talk_combo: str,
    stt_backend: str,
) -> None:
    from dictate.daemon import Daemon
    from dictate.provider_supervisor import ProviderSupervisor, make_remote_probe

    supervisor = ProviderSupervisor(preferred=stt_backend, probe_fn=make_remote_probe(stt_backend))
    output = _resolve_typing_output_or_exit(type_backend)
    daemon = Daemon(
        stt,
        output=output,
        language=language,
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
        supervisor=supervisor,
    )
    try:
        with _DaemonSignalHandlers(daemon):
            if sys.platform.startswith("win"):
                from dictate.windows_tray import WindowsTrayIcon

                WindowsTrayIcon(daemon).run()
                return

            from dictate.tray import TrayIcon

            TrayIcon(daemon).run()
    finally:
        supervisor.shutdown()


if __name__ == "__main__":
    raise SystemExit(main_with_logging())
