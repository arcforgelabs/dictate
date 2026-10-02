#!/usr/bin/env python3
"""CI proof that Meeting mode stays on the device and keeps dictated text out of logs.

Run by .github/workflows/privacy-proof.yml. Three subcommands:

``baseline``
    pyannote Community-1 diarizes the fixture without Dictate loaded, the way
    2026.9.27 left pyannote's metrics switch. Every Python-level socket call is
    recorded and refused, so the trace shows what pyannote tries to reach.

``meeting``
    One Meeting-mode pass through Dictate's own backend (pyannote speakers,
    Parakeet text) under the startup logger, with the same socket guard. The
    finished note goes through ``echo_dictated_text`` exactly as the daemon does
    when it saves a note. Run it under ``strace`` to see native code too.

``summarize``
    Checks both reports, the strace output, the terminal capture and
    ``latest.log``, prints a redacted trace and fails if anything leaked.

The trace never holds a token. Transcript text appears only in the terminal
capture, which is the one place Dictate is meant to show it; the fixture is
synthetic speech.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "", None}
_ATTEMPTS: list[dict[str, Any]] = []


class NetworkBlocked(OSError):
    """Raised in place of any outbound socket call during the trace."""


def _fmt_address(address: Any) -> str:
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return str(address)


def _is_loopback(host: Any) -> bool:
    return host in _LOOPBACK_HOSTS or (isinstance(host, str) and host.startswith("127."))


def install_network_guard() -> None:
    """Record and refuse every non-loopback socket call made from Python."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto

    def refuse(call: str, target: str) -> None:
        _ATTEMPTS.append({"call": call, "target": target})
        raise NetworkBlocked(f"privacy trace: {call} {target} refused")

    def is_inet(sock: socket.socket) -> bool:
        return sock.family in (socket.AF_INET, socket.AF_INET6)

    def getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN202
        if not _is_loopback(host):
            refuse("getaddrinfo", f"{host}:{port}")
        return real_getaddrinfo(host, port, *args, **kwargs)

    def connect(self, address):  # noqa: ANN001, ANN202
        if is_inet(self) and not _is_loopback(address[0]):
            refuse("connect", _fmt_address(address))
        return real_connect(self, address)

    def connect_ex(self, address):  # noqa: ANN001, ANN202
        if is_inet(self) and not _is_loopback(address[0]):
            refuse("connect_ex", _fmt_address(address))
        return real_connect_ex(self, address)

    def sendto(self, data, *args):  # noqa: ANN001, ANN202
        address = args[-1] if args else None
        if is_inet(self) and isinstance(address, tuple) and not _is_loopback(address[0]):
            refuse("sendto", _fmt_address(address))
        return real_sendto(self, data, *args)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise SystemExit(f"{path}: expected 16 kHz mono 16-bit PCM")
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def _flush_pyannote_metrics() -> bool | None:
    """Push any queued pyannote spans to the exporter now, and say whether metrics were on."""
    try:
        from pyannote.audio.telemetry import metrics
    except Exception:  # noqa: BLE001
        return None
    try:
        metrics.provider.force_flush()
    except Exception:  # noqa: BLE001
        pass
    try:
        return bool(metrics.is_metrics_enabled())
    except Exception:  # noqa: BLE001
        return None


def _summarise_attempts(attempts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        key = f"{attempt['call']} {attempt['target']}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_baseline(args: argparse.Namespace) -> int:
    # 2026.9.27 never set these, so pyannote and the Hub ran on their defaults.
    for name in ("PYANNOTE_METRICS_ENABLED", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ.pop(name, None)
    install_network_guard()
    if "dictate" in sys.modules:
        raise SystemExit("baseline must run without Dictate loaded")

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(str(args.pyannote_model))
    diarization = pipeline(str(args.audio))
    annotation = getattr(diarization, "exclusive_speaker_diarization", diarization)
    speakers = sorted({str(label) for _seg, _track, label in annotation.itertracks(yield_label=True)})
    metrics_enabled = _flush_pyannote_metrics()

    report = {
        "mode": "baseline (pyannote without Dictate, 2026.9.27 behaviour)",
        "dictate_imported": "dictate" in sys.modules,
        "pyannote_metrics_enabled": metrics_enabled,
        "speakers_found": len(speakers),
        "python_network_attempts": len(_ATTEMPTS),
        "otel_pyannote_lookups": sum(
            1 for a in _ATTEMPTS if a["call"] == "getaddrinfo" and "otel.pyannote.ai" in a["target"]
        ),
        "attempts": _summarise_attempts(_ATTEMPTS),
    }
    _write_report(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_meeting(args: argparse.Namespace) -> int:
    install_network_guard()

    # Importing anything from dictate runs the package initializer first.
    from dictate import runtime_logging
    from dictate.stt.parakeet_pyannote_backend import ParakeetPyannoteSpeechToText, _format_segments

    audio = _read_wav(args.audio)
    result: dict[str, Any] = {}

    def main() -> int:
        backend = ParakeetPyannoteSpeechToText(device="cpu")
        segments = backend.transcribe_diarized_segments(audio)
        note = _format_segments(segments).strip()
        result["segments"] = len(segments)
        result["speakers"] = len({s.speaker_label for s in segments if s.speaker_label})
        result["note"] = note
        # What daemon._finalize_note_session does once a meeting note is saved.
        runtime_logging.echo_dictated_text("Saved note", note)
        backend.release()
        return 0 if note else 1

    exit_code = runtime_logging.run_with_startup_logging(main)
    metrics_enabled = _flush_pyannote_metrics()
    log_paths = runtime_logging.resolve_log_paths()
    latest_log = log_paths[0] if log_paths else None
    log_text = latest_log.read_text(encoding="utf-8") if latest_log and latest_log.exists() else ""
    note = result.get("note", "")
    # Each speaker's words, without the "Speaker N: " label the log may legitimately share.
    phrases = [line.split(": ", 1)[-1].strip() for line in note.splitlines()]
    leaked_phrases = [phrase for phrase in phrases if phrase and phrase in log_text]
    ort_store = Path.home() / ".cache" / "Microsoft" / "DeveloperTools"

    report = {
        "mode": "meeting (Dictate Parakeet + pyannote backend)",
        "exit_code": exit_code,
        "env_after_import": {
            name: os.environ.get(name)
            for name in ("PYANNOTE_METRICS_ENABLED", "HF_HUB_DISABLE_TELEMETRY", "ORT_DISABLE_TELEMETRY")
        },
        "pyannote_metrics_enabled": metrics_enabled,
        "segments": result.get("segments", 0),
        "speakers": result.get("speakers", 0),
        "note_characters": len(note),
        "python_network_attempts": len(_ATTEMPTS),
        "otel_pyannote_lookups": sum(
            1 for a in _ATTEMPTS if a["call"] == "getaddrinfo" and "otel.pyannote.ai" in a["target"]
        ),
        "attempts": _summarise_attempts(_ATTEMPTS),
        "onnxruntime_telemetry_store_exists": ort_store.exists(),
        "latest_log": str(latest_log) if latest_log else None,
        "log_has_redacted_note_line": f"Saved note: [{len(note)} characters, not logged]" in log_text,
        "log_transcript_phrases_checked": len([p for p in phrases if p]),
        "log_transcript_phrases_found": len(leaked_phrases),
        "log_redacted_lines": [line.strip() for line in log_text.splitlines() if "not logged]" in line],
    }
    _write_report(args.report, report)
    # Kept beside the report only so summarize can check the terminal side; synthetic speech.
    args.report.with_name("note.txt").write_text(note, encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True), file=sys.stdout)
    return int(exit_code)


def _inet_syscalls(strace_path: Path) -> list[str]:
    if not strace_path.exists():
        raise SystemExit(f"missing strace output: {strace_path}")
    return [
        line.strip()
        for line in strace_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if "sa_family=AF_INET" in line
    ]


def cmd_summarize(args: argparse.Namespace) -> int:
    trace_dir: Path = args.trace_dir
    baseline = json.loads((trace_dir / "baseline.json").read_text(encoding="utf-8"))
    meeting = json.loads((trace_dir / "meeting.json").read_text(encoding="utf-8"))
    inet = _inet_syscalls(trace_dir / "strace.txt")
    note = (trace_dir / "note.txt").read_text(encoding="utf-8")
    terminal = (trace_dir / "terminal.txt").read_text(encoding="utf-8", errors="replace")
    first_line = note.splitlines()[0] if note else ""
    terminal_has_text = bool(first_line) and f"Saved note: {first_line}" in terminal

    checks = [
        ("baseline: pyannote tried otel.pyannote.ai (so the guard can see it)", baseline["otel_pyannote_lookups"] > 0),
        ("meeting: run finished and produced a note", meeting["exit_code"] == 0 and meeting["note_characters"] > 0),
        ("meeting: telemetry switches forced off over a shell opt-in", meeting["env_after_import"] == {
            "PYANNOTE_METRICS_ENABLED": "0", "HF_HUB_DISABLE_TELEMETRY": "1", "ORT_DISABLE_TELEMETRY": "1"
        }),
        ("meeting: pyannote metrics disabled", meeting["pyannote_metrics_enabled"] is False),
        ("meeting: 0 Python-level network attempts", meeting["python_network_attempts"] == 0),
        ("meeting: 0 AF_INET/AF_INET6 connect/send syscalls (strace -f)", not inet),
        ("meeting: no ONNX Runtime telemetry store", meeting["onnxruntime_telemetry_store_exists"] is False),
        ("log: finished note recorded as a character count", meeting["log_has_redacted_note_line"]),
        (
            f"log: none of the {meeting['log_transcript_phrases_checked']} spoken phrases appear",
            meeting["log_transcript_phrases_checked"] > 0 and meeting["log_transcript_phrases_found"] == 0,
        ),
        ("terminal (a TTY): note shown in full", terminal_has_text),
    ]

    lines = [
        "## Meeting-mode privacy trace",
        "",
        "| | Baseline: pyannote without Dictate (2026.9.27) | Meeting mode through Dictate |",
        "|---|---|---|",
        f"| `otel.pyannote.ai` lookups | {baseline['otel_pyannote_lookups']} | {meeting['otel_pyannote_lookups']} |",
        f"| Python-level network attempts | {baseline['python_network_attempts']} | {meeting['python_network_attempts']} |",
        f"| AF_INET/AF_INET6 syscalls (strace -f) | not traced | {len(inet)} |",
        f"| pyannote metrics enabled | {baseline['pyannote_metrics_enabled']} | {meeting['pyannote_metrics_enabled']} |",
        f"| Speakers | {baseline['speakers_found']} | {meeting['speakers']} |",
        "",
        "Baseline attempts (all refused):",
        "",
        "```",
        *(f"{count}x {target}" for target, count in sorted(baseline["attempts"].items())),
        "```",
        "",
        "`latest.log` lines for the finished note:",
        "",
        "```",
        *meeting["log_redacted_lines"],
        "```",
        "",
        "| Check | Result |",
        "|---|---|",
        *(f"| {name} | {'pass' if ok else 'FAIL'} |" for name, ok in checks),
    ]
    if inet:
        lines += ["", "Unexpected network syscalls:", "", "```", *inet[:50], "```"]
    summary = "\n".join(lines) + "\n"
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 0 if all(ok for _name, ok in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    baseline = sub.add_parser("baseline")
    baseline.add_argument("--pyannote-model", type=Path, required=True)
    baseline.add_argument("--audio", type=Path, required=True)
    baseline.add_argument("--report", type=Path, required=True)
    baseline.set_defaults(func=cmd_baseline)

    meeting = sub.add_parser("meeting")
    meeting.add_argument("--audio", type=Path, required=True)
    meeting.add_argument("--report", type=Path, required=True)
    meeting.set_defaults(func=cmd_meeting)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--trace-dir", type=Path, required=True)
    summarize.set_defaults(func=cmd_summarize)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
