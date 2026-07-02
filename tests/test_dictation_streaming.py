"""P0: dictation must assemble streamed chunks via overlap+merge, not a raw concat.

Drives the daemon's streaming decode path (the same prompt-tail-threaded merge
machinery the note streamer uses) with a fake local STT and asserts:
  - the assembled transcript is the overlap-MERGED result (seam deduped),
    not a naive " ".join of independently-decoded fragments;
  - the prompt tail from the first chunk is threaded into the second chunk's
    ``initial_prompt``;
  - EVERY dictation chunk decodes with ``long_form=False`` (cross-chunk continuity
    comes from the threaded ``initial_prompt``, not ``condition_on_previous_text``).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from dictate.audio import AudioChunk
from dictate.daemon import Daemon
from dictate.history import HistoryStore
from dictate.stt.base import SttCapabilities


class _FakeRecorder:
    """Minimal AudioRecorder double that just records start() kwargs."""

    def __init__(self) -> None:
        self.is_recording = False
        self.on_chunk = None
        self.recording_id = None
        self.start_kwargs: list[dict[str, object]] = []

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        self.is_recording = True
        self.on_chunk = on_chunk
        self.recording_id = recording_id
        self.start_kwargs.append(dict(kwargs))

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.array([], dtype=np.float32)


class _ScriptedStreamingStt:
    """Local streaming-capable STT that returns scripted text per call and records kwargs."""

    backend_name = "faster-whisper"
    model_name = "turbo"
    capabilities = SttCapabilities(supports_streaming_chunks=True)

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    @property
    def model(self):
        return None

    def transcribe(
        self,
        audio,
        language=None,
        hotwords=None,
        prompt_context=None,
        *,
        initial_prompt=None,
        long_form=False,
        decode_profile="quality",
    ):
        del audio, language, hotwords, prompt_context
        index = len(self.calls)
        self.calls.append(
            {
                "initial_prompt": initial_prompt,
                "long_form": long_form,
                "decode_profile": decode_profile,
            }
        )
        return self.responses[index]

    def release(self) -> None:
        pass


class DictationOverlapStreamAssemblyTests(unittest.TestCase):
    def test_two_chunk_utterance_merges_overlap_instead_of_raw_concat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ScriptedStreamingStt(
                [
                    "the quick brown fox jumps",
                    "fox jumps over the lazy dog",
                ]
            )
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon._start_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            self.assertIsNotNone(recorder.on_chunk)
            # Dictation streaming uses the overlap accumulator, not the fixed window.
            self.assertTrue(recorder.start_kwargs[-1]["overlap_stream"])

            mid_chunk = AudioChunk(
                samples=np.ones(16000, dtype=np.float32),
                final=False,
                sequence=0,
                recording_id=recording_id,
                stream_final=False,
            )
            daemon._handle_partial_chunk(mid_chunk)

            final_chunk = AudioChunk(
                samples=np.ones(16000, dtype=np.float32),
                final=False,
                sequence=1,
                recording_id=recording_id,
                stream_final=True,
            )
            daemon._handle_partial_chunk(final_chunk)

            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=recording_id)
            )

            # Assembled text must be the overlap-merged result: the "fox jumps" seam
            # is deduped, not doubled the way a raw concat would double it.
            assembled = output.send.call_args_list[0].args[0]
            self.assertEqual(assembled, "the quick brown fox jumps over the lazy dog")
            self.assertNotIn("fox jumps fox jumps", assembled)
            self.assertEqual(store.load()[0].text, assembled)

            # Prompt-tail threading: second call's initial_prompt carries the first
            # chunk's tail text.
            self.assertEqual(len(stt.calls), 2)
            self.assertIsNone(stt.calls[0]["initial_prompt"])
            self.assertEqual(stt.calls[1]["initial_prompt"], "the quick brown fox jumps")

            # Every dictation chunk decodes with long_form=False: cross-chunk
            # continuity comes from the threaded initial_prompt, not
            # condition_on_previous_text (anti-hallucination-safe OFF).
            self.assertFalse(stt.calls[0]["long_form"])
            self.assertFalse(stt.calls[1]["long_form"])

            # Dictation decodes with the QUALITY profile (beam5); notes get "note".
            self.assertEqual(stt.calls[0]["decode_profile"], "quality")
            self.assertEqual(stt.calls[1]["decode_profile"], "quality")


class _ProfileCapturingStt:
    """Streaming-capable local STT that records decode_profile + long_form it receives."""

    backend_name = "faster-whisper"
    model_name = "turbo"
    capabilities = SttCapabilities(supports_streaming_chunks=True)

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @property
    def model(self):
        return None

    def transcribe(self, audio, *args, decode_profile="quality", long_form=False, **kwargs):  # noqa: ANN001
        del audio, args, kwargs
        self.calls.append({"decode_profile": decode_profile, "long_form": long_form})
        return "text"

    def release(self) -> None:
        pass


class NoteVsDictationDecodeProfileTests(unittest.TestCase):
    """P2-2/P3-1: note stream chunks decode with the lighter 'note' profile (beam1)
    and long_form=True (unchanged); dictation stream chunks use the 'quality'
    profile (beam5) and long_form=False for every chunk."""

    def _seed(self, daemon, recording_id: int, mode: str, *, note: bool) -> None:  # noqa: ANN001
        daemon._recording_stt_ids[recording_id] = id(daemon.engine.stt)
        daemon._recording_parts[recording_id] = []
        daemon._recording_modes[recording_id] = mode
        daemon._streaming_recordings.add(recording_id)
        daemon._recording_prompt_tails[recording_id] = ""
        if note:
            daemon._note_streaming_recordings.add(recording_id)

    def test_decode_profile_per_mode_at_decode_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = MagicMock()
            output.name = "mock"
            stt = _ProfileCapturingStt()
            daemon = Daemon(
                stt,
                output=output,
                history_store=HistoryStore(path=Path(tmp) / "h.json"),
                recorder=_FakeRecorder(),
            )
            daemon.engine.min_duration_s = 0

            self._seed(daemon, 1, "dictation", note=False)
            daemon._transcribe_recording_audio(1, np.ones(16000, dtype=np.float32))
            self.assertEqual(stt.calls[-1]["decode_profile"], "quality")
            self.assertFalse(stt.calls[-1]["long_form"])

            self._seed(daemon, 2, "note", note=True)
            daemon._transcribe_recording_audio(2, np.ones(16000, dtype=np.float32))
            self.assertEqual(stt.calls[-1]["decode_profile"], "note")
            self.assertTrue(stt.calls[-1]["long_form"])


if __name__ == "__main__":
    unittest.main()
