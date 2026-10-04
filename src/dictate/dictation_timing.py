"""How long each step of one dictation took, for the log.

One line per dictation, from the moment the push-to-talk key is released to
the clipboard being put back. It holds durations and the audio length only,
never the dictated words (VISION.md: Dictate's logs do not record what was
said).

The line looks like::

    Dictation timing: audio=5.60s release_to_text=931ms stop=45ms wait=12ms
    decode=820ms fixes=0ms history=3ms paste=51ms | clipboard lock=0ms
    save=4ms write=1ms keys=25ms read=120ms restore=15ms | capture_processing=30ms

(on one line in the log). ``release_to_text`` is what a user waits for: key
release until the paste keystroke has been sent. ``stop``, ``wait``,
``decode``, ``fixes``, ``history`` and ``paste`` add up to it, give or take a
few milliseconds of bookkeeping. The ``clipboard`` part splits ``paste`` and
adds what happens after it: waiting for the target app to read the text and
putting the old clipboard back. ``capture_processing`` ran while the user was
speaking, so it is not part of ``release_to_text``.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Clock = Callable[[], float]


@dataclass(slots=True)
class DictationTiming:
    """Marks for one dictation, all from ``clock`` (``time.perf_counter``)."""

    clock: Clock = time.perf_counter
    released_at: float | None = None
    audio_s: float | None = None
    # Key release until the microphone stream is stopped and the last
    # preprocessed samples are flushed.
    stop_s: float | None = None
    stopped_at: float | None = None
    # Mic stopped until the decoder starts on the clip: the queue, the worker
    # picking it up, and the engine lock.
    wait_s: float | None = None
    # Speech-to-text inference after release, summed over the pieces decoded.
    decode_s: float = 0.0
    # Hotword and replacement corrections applied to the decoded text.
    fixes_s: float = 0.0
    history_s: float | None = None
    # Hand-off to the output backend until the paste keystroke has been sent.
    paste_s: float | None = None
    typed_at: float | None = None
    # Resampling and preprocessing on the live stream, summed over the whole
    # recording. It runs while the user speaks, not after release.
    capture_processing_s: float | None = None

    def __post_init__(self) -> None:
        if self.released_at is None:
            self.released_at = self.clock()

    def now(self) -> float:
        return self.clock()

    def mark_stopped(self) -> None:
        self.stopped_at = self.clock()
        self.stop_s = self.stopped_at - self.released_at

    def mark_decode_started(self) -> None:
        if self.wait_s is not None:
            return
        started = self.clock()
        self.wait_s = started - (self.stopped_at if self.stopped_at is not None else self.released_at)

    def add_decode(self, decode_s: object, fixes_s: object) -> None:
        if isinstance(decode_s, (int, float)):
            self.decode_s += max(0.0, float(decode_s))
        if isinstance(fixes_s, (int, float)):
            self.fixes_s += max(0.0, float(fixes_s))

    def mark_typed(self) -> None:
        self.typed_at = self.clock()

    @property
    def release_to_text_s(self) -> float | None:
        if self.typed_at is None:
            return None
        return self.typed_at - self.released_at

    def format_line(self, clipboard: Any | None = None) -> str:
        """The log line. ``clipboard`` is a ``PasteOutcome`` or None."""
        parts = [f"audio={_seconds(self.audio_s)}"]
        parts.append(f"release_to_text={_ms(self.release_to_text_s)}")
        parts.append(f"stop={_ms(self.stop_s)}")
        parts.append(f"wait={_ms(self.wait_s)}")
        parts.append(f"decode={_ms(self.decode_s)}")
        parts.append(f"fixes={_ms(self.fixes_s)}")
        parts.append(f"history={_ms(self.history_s)}")
        parts.append(f"paste={_ms(self.paste_s)}")
        line = "Dictation timing: " + " ".join(parts)
        if clipboard is not None:
            line += " | clipboard " + " ".join(
                (
                    f"lock={_ms(getattr(clipboard, 'lock_wait_s', None))}",
                    f"save={_ms(getattr(clipboard, 'save_s', None))}",
                    f"write={_ms(getattr(clipboard, 'write_s', None))}",
                    f"keys={_ms(getattr(clipboard, 'keys_s', None))}",
                    f"read={_ms(getattr(clipboard, 'read_wait_s', None))}",
                    f"restore={_ms(getattr(clipboard, 'restore_s', None))}",
                )
            )
        if self.capture_processing_s is not None:
            line += f" | capture_processing={_ms(self.capture_processing_s)}"
        return line


def log_timing_line(line: str) -> None:
    """Write one timing line to stderr, which the app mirrors into latest.log."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        # One write so a line from the clipboard thread is not split by another.
        stream.write(f"\r  {line}\n")
        stream.flush()
    except Exception:  # noqa: BLE001
        pass


def _ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{max(0.0, value) * 1000:.0f}ms"


def _seconds(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}s"
