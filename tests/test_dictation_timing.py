"""The per-dictation timing line: present, complete, and free of dictated text (#156)."""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

# Stub out heavy dependencies so the daemon imports without pynput / sounddevice.
for _mod_name, _attrs in {
    "pynput": {},
    "pynput.keyboard": {"Listener": MagicMock, "Key": MagicMock()},
    "sounddevice": {"InputStream": MagicMock},
}.items():
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        for _attr_name, _attr_val in _attrs.items():
            setattr(_mod, _attr_name, _attr_val)
        sys.modules[_mod_name] = _mod

from dictate.audio import SoundDeviceRecorder  # noqa: E402
from dictate.clipboard_keeper import ClipboardKeeper  # noqa: E402
from dictate.dictation_timing import DictationTiming  # noqa: E402
from dictate.engine import DictationEngine  # noqa: E402
from dictate.history import HistoryStore  # noqa: E402
from dictate.note_store import NoteStore  # noqa: E402
from dictate.outputs import PasteOutput  # noqa: E402
from dictate.stt.base import SttCapabilities  # noqa: E402

SECRET = "the quarterly numbers are confidential"


class _Stt:
    backend_name = "fake"
    model_name = "fake-model"
    capabilities = SttCapabilities()

    def __init__(self, text: str = SECRET) -> None:
        self.text = text

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del audio, args, kwargs
        return self.text

    def release(self) -> None:
        pass


class _Recorder:
    """One second of audio, with the capture-processing figure a real recorder keeps."""

    def __init__(self) -> None:
        self.is_recording = False
        self.truncated = False
        self.last_processing_seconds: float | None = None

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        del on_chunk, recording_id, kwargs
        self.is_recording = True

    def stop(self) -> np.ndarray:
        self.is_recording = False
        self.last_processing_seconds = 0.004
        return np.full(16000, 0.1, dtype=np.float32)


class _Session:
    """A clipboard with no read signal, so the keeper waits a fixed (zero) delay."""

    has_read_signal = False
    settle_seconds = 0.0
    handles_primary = False

    def __init__(self) -> None:
        self.value = "copied earlier"
        self.written: str | None = None

    def snapshot(self) -> str:
        return self.value

    def write_text(self, text: str) -> None:
        self.value = text
        self.written = text

    def before_paste(self) -> None:
        pass

    def target_has_read(self) -> bool:
        return False

    def wait(self, seconds: float) -> None:
        del seconds

    def changed_since_write(self) -> bool:
        return self.value != self.written

    def restore(self, snapshot: str) -> None:
        self.value = snapshot

    def close(self) -> None:
        pass


def _timing_lines(log: str) -> list[str]:
    return [
        line.strip()
        for line in log.replace("\r", "\n").splitlines()
        if line.strip().startswith("Dictation timing:")
    ]


class DaemonTimingLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _daemon(self, output, stt=None):  # noqa: ANN001
        from dictate.daemon import Daemon

        return Daemon(
            stt or _Stt(),
            output=output,
            history_store=HistoryStore(path=self.root / "h.json"),
            note_store=NoteStore(self.root / "notes"),
            recorder=_Recorder(),
        )

    def _dictate(self, daemon) -> str:  # noqa: ANN001
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.assertTrue(daemon._start_recording())
            daemon._finalize_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())
        return log.getvalue()

    def test_one_timing_line_per_dictation_with_every_step_and_no_text(self) -> None:
        output = MagicMock()
        output.name = "mock"
        daemon = self._daemon(output)

        log = self._dictate(daemon)

        output.send.assert_called_once_with(SECRET)
        lines = _timing_lines(log)
        self.assertEqual(len(lines), 1, log)
        line = lines[0]
        self.assertIn("audio=1.00s", line)
        for step in ("release_to_text", "stop", "wait", "decode", "fixes", "history", "paste"):
            self.assertRegex(line, rf"\b{step}=\d+ms\b")
        self.assertIn("capture_processing=4ms", line)
        # No output keeper: no clipboard part.
        self.assertNotIn("clipboard", line)
        # Neither the timing line nor anything else in the log carries the words.
        self.assertNotIn(SECRET, log)
        for word in SECRET.split():
            self.assertNotIn(word, line)
        self.assertEqual(daemon._recording_timings, {})

    def test_steps_add_up_to_release_to_text(self) -> None:
        output = MagicMock()
        output.name = "mock"
        line = _timing_lines(self._dictate(self._daemon(output)))[0]
        values = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)ms", line)}
        steps = sum(values[key] for key in ("stop", "wait", "decode", "fixes", "history", "paste"))
        # Rounding each step to a millisecond, plus bookkeeping between steps.
        self.assertLessEqual(steps, values["release_to_text"] + 6)

    def test_clipboard_part_is_logged_after_the_restore(self) -> None:
        session = _Session()
        keeper = ClipboardKeeper(lambda plain_text: session, no_signal_delay=0.0, background=False)
        output = PasteOutput(typing_output=MagicMock(), clipboard_output=MagicMock(), keeper=keeper)
        daemon = self._daemon(output)

        with patch("dictate.outputs._send_paste_shortcut"):
            log = self._dictate(daemon)

        self.assertEqual(session.value, "copied earlier")
        lines = _timing_lines(log)
        self.assertEqual(len(lines), 1, log)
        clipboard = lines[0].split("| clipboard ", 1)[1]
        for step in ("lock", "save", "write", "keys", "read", "restore"):
            self.assertRegex(clipboard, rf"\b{step}=\d+ms\b")
        self.assertNotIn(SECRET, log)

    def test_no_speech_logs_no_timing_and_keeps_nothing(self) -> None:
        output = MagicMock()
        output.name = "mock"
        daemon = self._daemon(output, stt=_Stt(text=""))

        log = self._dictate(daemon)

        output.send.assert_not_called()
        self.assertEqual(_timing_lines(log), [])
        self.assertEqual(daemon._recording_timings, {})

    def test_failed_output_logs_no_timing(self) -> None:
        output = MagicMock()
        output.name = "mock"
        output.send.side_effect = RuntimeError("no focus")
        daemon = self._daemon(output)

        log = self._dictate(daemon)

        self.assertEqual(_timing_lines(log), [])
        self.assertEqual(daemon._recording_timings, {})

    def test_transcribing_line_says_it_is_the_audio_length(self) -> None:
        output = MagicMock()
        output.name = "mock"
        log = self._dictate(self._daemon(output))
        self.assertIn("Transcribing 1.0 s of audio", log)


class DictationTimingFormatTests(unittest.TestCase):
    def test_line_from_marks(self) -> None:
        now = [10.0]
        timing = DictationTiming(clock=lambda: now[0])
        now[0] = 10.050
        timing.mark_stopped()
        now[0] = 10.060
        timing.mark_decode_started()
        timing.add_decode(0.800, 0.001)
        timing.audio_s = 5.6
        timing.history_s = 0.003
        timing.paste_s = 0.040
        now[0] = 10.905
        timing.mark_typed()

        line = timing.format_line()

        self.assertEqual(
            line,
            "Dictation timing: audio=5.60s release_to_text=905ms stop=50ms wait=10ms "
            "decode=800ms fixes=1ms history=3ms paste=40ms",
        )

    def test_missing_steps_show_a_dash(self) -> None:
        timing = DictationTiming(clock=lambda: 1.0)
        self.assertEqual(
            timing.format_line(),
            "Dictation timing: audio=- release_to_text=- stop=- wait=- "
            "decode=0ms fixes=0ms history=- paste=-",
        )

    def test_non_numeric_decode_figures_are_ignored(self) -> None:
        timing = DictationTiming(clock=lambda: 1.0)
        timing.add_decode(MagicMock(), None)
        self.assertEqual(timing.decode_s, 0.0)


class KeeperTimingTests(unittest.TestCase):
    def test_paste_returns_a_future_with_step_timings(self) -> None:
        session = _Session()
        keeper = ClipboardKeeper(lambda plain_text: session, no_signal_delay=0.0)

        future = keeper.paste("words", lambda: None)
        outcome = future.result(timeout=5)

        self.assertTrue(outcome.restored)
        for name in ("lock_wait_s", "save_s", "write_s", "keys_s", "read_wait_s", "restore_s"):
            value = getattr(outcome, name)
            self.assertIsInstance(value, float, name)
            self.assertGreaterEqual(value, 0.0, name)
        self.assertEqual(session.value, "copied earlier")


class EngineTimingTests(unittest.TestCase):
    def test_result_carries_decode_and_fix_seconds(self) -> None:
        engine = DictationEngine(_Stt(text="hello"))
        result = engine.transcribe(np.full(16000, 0.1, dtype=np.float32))
        self.assertEqual(result.status, "ok")
        self.assertIsInstance(result.stt_s, float)
        self.assertIsInstance(result.fixes_s, float)

    def test_stream_chunk_result_carries_decode_seconds(self) -> None:
        engine = DictationEngine(_Stt(text="hello"))
        result = engine.transcribe_stream_chunk(np.full(16000, 0.1, dtype=np.float32))
        self.assertIsInstance(result.stt_s, float)


class RecorderProcessingTimeTests(unittest.TestCase):
    def test_stop_keeps_the_time_spent_resampling(self) -> None:
        recorder = SoundDeviceRecorder(sample_rate=16000, max_recording_seconds=2)
        stream = MagicMock()

        class _SD:
            default = SimpleNamespace(device=(0, 0))

            @staticmethod
            def query_devices(index=None):  # noqa: ANN001
                devices = [{"name": "hw:0,0", "max_input_channels": 1, "default_samplerate": 48000.0}]
                return devices if index is None else devices[index]

            @staticmethod
            def check_input_settings(**kwargs):  # noqa: ANN003
                if kwargs.get("samplerate") != 48000:
                    raise RuntimeError("bad rate")

            @staticmethod
            def InputStream(**kwargs):  # noqa: ANN003, N802
                stream.callback = kwargs["callback"]
                return stream

        self.assertIsNone(recorder.last_processing_seconds)
        with patch.dict("sys.modules", {"sounddevice": _SD}):
            with patch("dictate.audio.create_preprocessor", return_value=None):
                recorder.start()
        stream.callback(np.ones((48000, 1), dtype=np.float32), 48000, None, None)
        audio = recorder.stop()

        self.assertEqual(audio.shape[0], 16000)
        self.assertIsInstance(recorder.last_processing_seconds, float)
        self.assertGreater(recorder.last_processing_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
