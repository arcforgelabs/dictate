"""Environment checks for predictable runtime behavior."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from dictate.hotkey_backend import (
    HotkeyBackendUnavailableError,
    detect_hotkey_backend,
    portal_global_shortcuts_available,
)
from dictate.outputs import (
    BackendUnavailableError,
    clipboard_backend_available,
    detect_session_type,
    resolve_typing_backend,
)
from dictate.hotkey import format_hotkey_combo, normalize_push_to_talk_combo
from dictate.stt import ComputeDevice, SttBackend, check_backend_readiness


@dataclass(slots=True)
class PreflightReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def run_preflight(
    *,
    require_typing: bool,
    require_clipboard: bool,
    typing_backend: str = "auto",
    push_to_talk_combo: str = "ctrl_r",
    stt_backend: SttBackend = "faster-whisper",
    stt_model: str | None = None,
    stt_device: ComputeDevice = "auto",
) -> PreflightReport:
    report = PreflightReport()

    _check_microphone(report)
    _check_stt_backend(
        report,
        stt_backend=stt_backend,
        stt_model=stt_model,
        stt_device=stt_device,
    )
    _check_typing(
        report,
        require_typing=require_typing,
        typing_backend=typing_backend,
        push_to_talk_combo=push_to_talk_combo,
    )
    _check_clipboard(report, require_clipboard=require_clipboard)
    return report


def _check_microphone(report: PreflightReport) -> None:
    result: dict[str, object] = {}

    def query_devices() -> None:
        try:
            import sounddevice as sd

            result["devices"] = sd.query_devices()
            result["default"] = sd.default.device
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=query_devices, daemon=True)
    thread.start()
    thread.join(timeout=3.0)

    if thread.is_alive():
        report.warnings.append("Audio device probe timed out; skipping microphone preflight checks.")
        return

    error = result.get("error")
    if error is not None:
        report.errors.append(f"Could not query audio devices: {error}")
        return

    devices = result.get("devices")
    try:
        input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
    except Exception:  # noqa: BLE001
        report.warnings.append("Unable to inspect microphone devices.")
        return
    if not input_devices:
        report.errors.append("No microphone input devices detected.")

    default_pair = result.get("default")
    try:
        default_input = default_pair[0]  # type: ignore[index]
    except Exception:  # noqa: BLE001
        report.warnings.append("Unable to determine the default input device.")
    else:
        if default_input is None or default_input < 0:
            report.warnings.append("No default input device configured.")


def _check_stt_backend(
    report: PreflightReport,
    *,
    stt_backend: SttBackend,
    stt_model: str | None,
    stt_device: ComputeDevice,
) -> None:
    backend_report = check_backend_readiness(
        backend=stt_backend,
        model=stt_model,
        device=stt_device,
    )
    report.errors.extend(backend_report.errors)
    report.warnings.extend(backend_report.warnings)
    report.notes.extend(backend_report.notes)


def _check_typing(
    report: PreflightReport,
    *,
    require_typing: bool,
    typing_backend: str,
    push_to_talk_combo: str,
) -> None:
    if not require_typing:
        return

    session = detect_session_type()
    report.notes.append(f"Session type: {session}")
    report.notes.append(f"Push-to-talk combo: {format_hotkey_combo(normalize_push_to_talk_combo(push_to_talk_combo))}")

    try:
        backend = resolve_typing_backend(preferred=typing_backend)
    except BackendUnavailableError as exc:
        report.errors.append(str(exc))
        return

    report.notes.append(f"Typing backend: {backend.name}")
    try:
        hotkey_backend = detect_hotkey_backend()
    except HotkeyBackendUnavailableError as exc:
        report.errors.append(str(exc))
        hotkey_backend = None
    if hotkey_backend is not None:
        report.notes.append(f"Hotkey backend: {hotkey_backend}")
    if session == "wayland":
        if hotkey_backend == "portal":
            report.notes.append("Wayland hotkeys will use the desktop portal GlobalShortcuts API.")
        elif portal_global_shortcuts_available():
            report.warnings.append(
                "The desktop portal is available but not selected as the hotkey backend."
            )
        else:
            report.warnings.append(
                "Wayland desktop portal GlobalShortcuts is not available; global push-to-talk will not be reliable."
            )


def _check_clipboard(report: PreflightReport, *, require_clipboard: bool) -> None:
    if not require_clipboard:
        return
    if not clipboard_backend_available():
        report.errors.append("no clipboard backend found; install xclip or pyperclip.")
