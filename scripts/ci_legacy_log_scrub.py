"""Before/after proof that startup scrubs dictated text from older logs.

Writes synthetic logs in the format Dictate 2026.9.27 and earlier wrote
("Typed: <words>", "Saved note: <words>") into every log dir the scrub covers
(primary, temp fallback, pre-May-2026 legacy), plus a history file and a note
that hold the same words, all under a scratch dir. Then it starts the real
entrypoint (``python -m dictate --version``) with HOME, XDG_DATA_HOME or
LOCALAPPDATA, and the temp dir pointed at that scratch dir, prints every file
before and after, and fails if:

- a dictated word is left in any log,
- a log line other than the dictated ones changed,
- the history file or the note changed by a single byte,
- startup warned or did not exit 0,
- a second start rewrote anything.

The shared ``/tmp/dictate-logs`` legacy dir cannot be redirected, so it is
seeded only on a CI runner (``GITHUB_ACTIONS=true``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORDS = ("please email Alex the contract", "call the dentist about Thursday")

# What 2026.9.27 wrote: the recording indicator has no newline, so the next
# line starts after a carriage return on the same line.
OLD_LOG = (
    "dictate: startup at 2026-09-27T10:00:00+09:30\n"
    f"\r  \x1b[91m● Recording...\x1b[0m\r  Typed: {WORDS[0]}\n"
    f"\r  Saved note: {WORDS[1]}\n"
    "\r  Microphone error: device busy\n"
    "dictate: exit code 1\n"
)
SCRUBBED_LOG = (
    "dictate: startup at 2026-09-27T10:00:00+09:30\n"
    f"\r  \x1b[91m● Recording...\x1b[0m\r  Typed: [{len(WORDS[0])} characters, not logged]\n"
    f"\r  Saved note: [{len(WORDS[1])} characters, not logged]\n"
    "\r  Microphone error: device busy\n"
    "dictate: exit code 1\n"
)

PATHS_PROBE = (
    "import json; from dictate import runtime_logging as r; "
    "print(json.dumps({'primary': str(r.LOG_DIR), 'fallback': str(r.FALLBACK_LOG_DIR), "
    "'legacy': [str(p) for p in r.LEGACY_LOG_DIRS]}))"
)


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    home = root / "home"
    temp = root / "tmp"
    data = root / "data"
    for path in (home, temp, data):
        path.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_DATA_HOME": str(data),
            "LOCALAPPDATA": str(data),
            "TMPDIR": str(temp),
            "TMP": str(temp),
            "TEMP": str(temp),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    env.pop("DICTATE_DISABLE_STARTUP_LOG", None)
    return env


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _read(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _show(title: str, files: list[Path]) -> None:
    print(f"===== {title} =====")
    for path in files:
        print(f"--- {path}")
        for line in _read(path).splitlines(keepends=True):
            print(f"    {line!r}")


def _snapshot(files: list[Path]) -> dict[Path, tuple[int, int]]:
    return {path: (path.stat().st_mtime_ns, path.stat().st_size) for path in files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, help="scratch dir (default: a new temp dir)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # the fixture has a non-ASCII indicator
    root = (args.root or Path(tempfile.mkdtemp(prefix="dictate-scrub-proof-"))).resolve()
    env = _env(root)

    probe = subprocess.run(
        [sys.executable, "-c", PATHS_PROBE], env=env, capture_output=True, text=True, check=True
    )
    dirs = json.loads(probe.stdout)
    print(f"log dirs under this environment: {json.dumps(dirs, indent=2)}")

    primary = Path(dirs["primary"])
    log_dirs = [primary, Path(dirs["fallback"]), *(Path(p) for p in dirs["legacy"])]
    seeded_dirs: list[Path] = []
    for log_dir in log_dirs:
        if log_dir in seeded_dirs:
            continue
        if root not in log_dir.parents and os.environ.get("GITHUB_ACTIONS") != "true":
            print(f"skipping {log_dir}: outside the scratch dir and not on a CI runner")
            continue
        seeded_dirs.append(log_dir)

    active_latest = primary / "latest.log"
    logs = [d / name for d in seeded_dirs for name in ("latest.log", "last_failure.log")]
    scrubbed_logs = [path for path in logs if path != active_latest]
    data_dir = primary.parent
    keep = {
        data_dir / "recent-history.json": json.dumps(
            [{"text": f"Typed: {WORDS[0]}"}, {"text": f"Saved note: {WORDS[1]}"}]
        )
        + "\n",
        data_dir / "notes" / "20260927-100000" / "transcript.txt": f"Saved note: {WORDS[1]}\n",
        primary / "notes.txt": OLD_LOG,
    }
    for path in logs:
        _write(path, OLD_LOG)
    for path, content in keep.items():
        _write(path, content)

    _show("BEFORE", logs + list(keep))

    command = [sys.executable, "-m", "dictate", "--version"]
    print(f"===== RUN: {' '.join(command)} =====")
    first = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
    print(f"exit code {first.returncode}")
    print(first.stdout + first.stderr)

    _show("AFTER", logs + list(keep))

    failures: list[str] = []
    if first.returncode != 0:
        failures.append(f"dictate --version exited {first.returncode}")
    if "could not remove" in first.stderr:
        failures.append("startup warned that it could not scrub a log")
    for path in scrubbed_logs:
        if _read(path) != SCRUBBED_LOG:
            failures.append(f"{path} is not the expected scrubbed log")
    latest = _read(active_latest)
    if "dictate: startup at" not in latest or any(word in latest for word in WORDS):
        failures.append(f"{active_latest} was not replaced by this run's log")
    for path in logs:
        if any(word in _read(path) for word in WORDS):
            failures.append(f"dictated text left in {path}")
    for path, content in keep.items():
        if _read(path) != content:
            failures.append(f"{path} changed; only Dictate's log files may be touched")

    before_second = _snapshot(scrubbed_logs + list(keep))
    second = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
    if second.returncode != 0:
        failures.append(f"second dictate --version exited {second.returncode}")
    if _snapshot(scrubbed_logs + list(keep)) != before_second:
        failures.append("second start rewrote a file; the scrub should be a no-op by then")

    print("===== RESULT =====")
    print(f"older logs checked: {len(scrubbed_logs)}; active log replaced: {active_latest}")
    print(f"non-log files checked unchanged: {len(keep)} (history, a note, another file in the log dir)")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
