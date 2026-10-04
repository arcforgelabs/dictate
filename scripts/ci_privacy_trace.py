#!/usr/bin/env python3
"""CI proof that a note stays on the device and keeps dictated text out of logs.

Run by .github/workflows/privacy-proof.yml. Two subcommands:

``note``
    One note-mode pass through Dictate's own engine (Parakeet on ONNX Runtime)
    under the startup logger, with every Python-level socket call recorded and
    refused. The finished note goes through ``echo_dictated_text`` exactly as
    the daemon does when it saves a note. Run it under ``strace`` to see native
    code too.

``summarize``
    Checks the report, the strace output, the terminal capture and
    ``latest.log``, prints a redacted trace and fails if anything leaked.

Until #140 this also traced Meeting mode (pyannote); Meeting was removed, so
the Parakeet path every note and dictation takes is what is left to prove.

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
_TELEMETRY_SWITCHES = ("HF_HUB_DISABLE_TELEMETRY", "ORT_DISABLE_TELEMETRY")


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


def _summarise_attempts(attempts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        key = f"{attempt['call']} {attempt['target']}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_note(args: argparse.Namespace) -> int:
    install_network_guard()

    # Importing anything from dictate runs the package initializer first.
    from dictate import runtime_logging
    from dictate.engine import DictationEngine
    from dictate.stt import create_speech_to_text

    audio = _read_wav(args.audio)
    result: dict[str, Any] = {}

    def main() -> int:
        stt = create_speech_to_text(backend="parakeet", model="parakeet-tdt-0.6b-v2")
        engine = DictationEngine(stt=stt)
        # What the daemon does for a note recording: the note decode profile.
        transcribed = engine.transcribe(audio, decode_profile="note")
        note = transcribed.text.strip()
        result["status"] = transcribed.status
        result["note"] = note
        # What daemon._finalize_note_session does once a note is saved.
        runtime_logging.echo_dictated_text("Saved note", note)
        engine.release()
        return 0 if note else 1

    exit_code = runtime_logging.run_with_startup_logging(main)
    log_paths = runtime_logging.resolve_log_paths()
    latest_log = log_paths[0] if log_paths else None
    log_text = latest_log.read_text(encoding="utf-8") if latest_log and latest_log.exists() else ""
    note = result.get("note", "")
    words = [word.strip(".,!?").lower() for word in note.split()]
    phrase = " ".join(note.split()[:4])
    ort_store = Path.home() / ".cache" / "Microsoft" / "DeveloperTools"
    loaded = sorted(
        name for name in ("torch", "torchaudio", "torchcodec", "pyannote") if name in sys.modules
    )

    report = {
        "mode": "note (Dictate Parakeet backend)",
        "exit_code": exit_code,
        "status": result.get("status"),
        "env_after_import": {name: os.environ.get(name) for name in _TELEMETRY_SWITCHES},
        "removed_runtimes_loaded": loaded,
        "note_characters": len(note),
        "note_words": len(words),
        "python_network_attempts": len(_ATTEMPTS),
        "attempts": _summarise_attempts(_ATTEMPTS),
        "onnxruntime_telemetry_store_exists": ort_store.exists(),
        "latest_log": str(latest_log) if latest_log else None,
        "log_has_redacted_note_line": f"Saved note: [{len(note)} characters, not logged]" in log_text,
        "log_has_note_phrase": bool(phrase) and phrase in log_text,
        "log_redacted_lines": [line.strip() for line in log_text.splitlines() if "not logged]" in line],
    }
    _write_report(args.report, report)
    # Kept beside the report only so summarize can check the terminal side; synthetic speech.
    args.report.with_name("note.txt").write_text(note, encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True), file=sys.stdout)
    return int(exit_code)


def _strace_lines(strace_path: Path) -> list[str]:
    if not strace_path.exists():
        raise SystemExit(f"missing strace output: {strace_path}")
    return [
        line.strip()
        for line in strace_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]


def cmd_summarize(args: argparse.Namespace) -> int:
    trace_dir: Path = args.trace_dir
    note_report = json.loads((trace_dir / "note.json").read_text(encoding="utf-8"))
    traced = _strace_lines(trace_dir / "strace.txt")
    # execve is traced only to show strace was attached to the engine process.
    engine_exec = [line for line in traced if "execve(" in line and "ci_privacy_trace.py" in line]
    traced_pids = {line.split(maxsplit=1)[0] for line in traced if line[:1].isdigit()}
    inet = [line for line in traced if "sa_family=AF_INET" in line]
    note = (trace_dir / "note.txt").read_text(encoding="utf-8")
    terminal = (trace_dir / "terminal.txt").read_text(encoding="utf-8", errors="replace")
    terminal_has_text = bool(note) and f"Saved note: {note}" in terminal

    checks = [
        ("note: run finished and produced text", note_report["exit_code"] == 0 and note_report["note_characters"] > 0),
        ("note: telemetry switches forced off over a shell opt-in", note_report["env_after_import"] == {
            "HF_HUB_DISABLE_TELEMETRY": "1", "ORT_DISABLE_TELEMETRY": "1"
        }),
        ("note: no torch or pyannote module loaded", note_report["removed_runtimes_loaded"] == []),
        ("note: 0 Python-level network attempts", note_report["python_network_attempts"] == 0),
        ("note: strace -f was attached to the engine process", bool(engine_exec)),
        ("note: 0 AF_INET/AF_INET6 connect/send syscalls (strace -f)", not inet),
        ("note: no ONNX Runtime telemetry store", note_report["onnxruntime_telemetry_store_exists"] is False),
        ("log: finished note recorded as a character count", note_report["log_has_redacted_note_line"]),
        ("log: the spoken text does not appear", note_report["log_has_note_phrase"] is False),
        ("terminal (a TTY): note shown in full", terminal_has_text),
    ]

    lines = [
        "## Note-mode privacy trace (Parakeet)",
        "",
        "| | Note through Dictate |",
        "|---|---|",
        f"| Python-level network attempts | {note_report['python_network_attempts']} |",
        f"| AF_INET/AF_INET6 syscalls (strace -f) | {len(inet)} |",
        f"| strace -f: traced syscall lines / processes+threads | {len(traced)} / {len(traced_pids)} |",
        f"| Words transcribed | {note_report['note_words']} |",
        "",
        "`latest.log` lines for the finished note:",
        "",
        "```",
        *note_report["log_redacted_lines"],
        "```",
        "",
        "| Check | Result |",
        "|---|---|",
        *(f"| {name} | {'pass' if ok else 'FAIL'} |" for name, ok in checks),
    ]
    if inet:
        lines += ["", "Unexpected network syscalls:", "", "```", *inet[:50], "```"]
    if note_report["attempts"]:
        lines += ["", "Refused attempts:", "", "```"]
        lines += [f"{count}x {target}" for target, count in sorted(note_report["attempts"].items())]
        lines += ["```"]
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

    note = sub.add_parser("note")
    note.add_argument("--audio", type=Path, required=True)
    note.add_argument("--report", type=Path, required=True)
    note.set_defaults(func=cmd_note)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--trace-dir", type=Path, required=True)
    summarize.set_defaults(func=cmd_summarize)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
