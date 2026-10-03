"""Tests for microphone device selection and resampling."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from dictate.audio import (
    AudioCaptureError,
    SoundDeviceRecorder,
    resample_audio,
    resolve_input_capture,
)


class ResampleAudioTests(unittest.TestCase):
    def test_identity_when_rates_match(self) -> None:
        audio = np.linspace(-0.5, 0.5, 16, dtype=np.float32)
        out = resample_audio(audio, 16000, 16000)
        np.testing.assert_array_equal(out, audio)

    def test_empty_passthrough(self) -> None:
        out = resample_audio(np.array([], dtype=np.float32), 48000, 16000)
        self.assertEqual(out.size, 0)

    def test_downsamples_duration(self) -> None:
        # One second at 48 kHz -> one second at 16 kHz.
        audio = np.ones(48000, dtype=np.float32)
        out = resample_audio(audio, 48000, 16000)
        self.assertEqual(out.shape[0], 16000)
        self.assertTrue(np.allclose(out, 1.0, atol=1e-5))


class ResolveInputCaptureTests(unittest.TestCase):
    def _sd(
        self,
        *,
        default: int,
        devices: list[dict],
        supported: dict[tuple[int, int], bool],
    ) -> MagicMock:
        sd = MagicMock()
        sd.default = SimpleNamespace(device=(default, default))
        sd.query_devices.side_effect = lambda index=None: (
            devices if index is None else devices[index]
        )
        sd.query_hostapis.return_value = []

        def check_input_settings(*, device, samplerate, **_kwargs):
            if not supported.get((device, samplerate), False):
                raise RuntimeError(f"unsupported {device}@{samplerate}")

        sd.check_input_settings.side_effect = check_input_settings
        return sd

    def test_uses_default_when_it_supports_target_rate(self) -> None:
        devices = [
            {"name": "hw:0,0", "max_input_channels": 2, "default_samplerate": 44100.0},
            {"name": "sysdefault", "max_input_channels": 128, "default_samplerate": 48000.0},
        ]
        sd = self._sd(
            default=0,
            devices=devices,
            supported={(0, 16000): True, (1, 16000): True},
        )
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (0, 16000))

    def test_prefers_pulse_hostapi_default(self) -> None:
        devices = [
            {"name": "hw:0,0", "max_input_channels": 2, "default_samplerate": 44100.0},
            {"name": "Default Source", "max_input_channels": 32, "default_samplerate": 48000.0},
            {"name": "sysdefault", "max_input_channels": 128, "default_samplerate": 48000.0},
        ]
        sd = self._sd(
            default=0,
            devices=devices,
            supported={(0, 16000): False, (1, 16000): True, (2, 16000): True},
        )
        sd.query_hostapis.return_value = [
            {"name": "ALSA", "default_input_device": 0},
            {"name": "PulseAudio", "default_input_device": 1},
        ]
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (1, 16000))

    def test_prefers_sysdefault_when_hw_rejects_16k(self) -> None:
        # Ubuntu 26 / packaged PortAudio: default is raw hw, 16 kHz invalid.
        devices = [
            {"name": "HDA Intel PCH: Analog (hw:0,0)", "max_input_channels": 2, "default_samplerate": 44100.0},
            {"name": "sysdefault", "max_input_channels": 128, "default_samplerate": 48000.0},
        ]
        sd = self._sd(
            default=0,
            devices=devices,
            supported={(0, 16000): False, (0, 44100): True, (1, 16000): True},
        )
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (1, 16000))

    def test_falls_back_to_native_rate_when_needed(self) -> None:
        devices = [
            {"name": "hw:0,0", "max_input_channels": 2, "default_samplerate": 44100.0},
        ]
        sd = self._sd(
            default=0,
            devices=devices,
            supported={(0, 16000): False, (0, 44100): True},
        )
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (0, 44100))

    def test_reads_default_from_sounddevice_pair_object(self) -> None:
        # sounddevice.default.device is an _InputOutputPair: indexable, not a
        # list or tuple. Windows names its microphones after the hardware, so
        # the default is the only way in; losing it meant "no microphone".
        class Pair:
            def __init__(self, values):
                self._values = values

            def __getitem__(self, index):
                return self._values[index]

        devices = [
            {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "default_samplerate": 44100.0},
            {"name": "Microphone (Scarlett Solo USB)", "max_input_channels": 2, "default_samplerate": 44100.0},
        ]
        sd = self._sd(default=0, devices=devices, supported={(1, 16000): True, (0, 16000): True})
        sd.default = SimpleNamespace(device=Pair([1, 3]))
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (1, 16000))

    def test_uses_portaudio_default_input_query_when_pair_is_unset(self) -> None:
        devices = [
            {"name": "Microphone (AUDIO 2.0)", "max_input_channels": 2, "default_samplerate": 48000.0},
            {"name": "Microphone (2- Antlion Wireless Microphone)", "max_input_channels": 1, "default_samplerate": 48000.0},
        ]
        sd = self._sd(default=-1, devices=devices, supported={(0, 16000): True, (1, 16000): True})

        def query_devices(index=None, kind=None):
            if kind == "input":
                return {**devices[1], "index": 1}
            return devices if index is None else devices[index]

        sd.query_devices.side_effect = query_devices
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (1, 16000))

    def test_falls_back_to_any_input_device_without_a_default(self) -> None:
        # Windows: no PulseAudio, no default reported, hardware-named devices.
        devices = [
            {"name": "Speakers (Realtek(R) Audio)", "max_input_channels": 0, "default_samplerate": 48000.0},
            {"name": "Microphone (2- RIG 800HX)", "max_input_channels": 2, "default_samplerate": 44100.0},
        ]
        sd = self._sd(default=-1, devices=devices, supported={(1, 16000): True})
        device, rate = resolve_input_capture(sd, target_rate=16000)
        self.assertEqual((device, rate), (1, 16000))

    def test_real_sounddevice_default_pair_is_indexable(self) -> None:
        try:
            import sounddevice
        except Exception as exc:  # noqa: BLE001 - PortAudio missing on this host
            self.skipTest(f"sounddevice unavailable: {exc}")
        # Other tests may leave a stub module in sys.modules; only the real
        # library has the pair class this test is about.
        if not hasattr(sounddevice, "_InputOutputPair") or not hasattr(sounddevice, "default"):
            self.skipTest("sounddevice in sys.modules is a test stub, not the library")
        pair = sounddevice.default.device
        self.assertIsInstance(pair, sounddevice._InputOutputPair)
        self.assertNotIsInstance(pair, (list, tuple))
        from dictate.audio import _default_input_device

        expected = int(pair[0])
        self.assertEqual(_default_input_device(sounddevice), expected if expected >= 0 else None)

    def test_raises_when_nothing_works(self) -> None:
        devices = [
            {"name": "hw:0,0", "max_input_channels": 2, "default_samplerate": 44100.0},
        ]
        sd = self._sd(default=0, devices=devices, supported={})
        with self.assertRaises(AudioCaptureError):
            resolve_input_capture(sd, target_rate=16000)


class SoundDeviceRecorderCaptureTests(unittest.TestCase):
    def test_start_opens_resolved_device_and_resamples_callback(self) -> None:
        seen: list[np.ndarray] = []
        recorder = SoundDeviceRecorder(sample_rate=16000, max_recording_seconds=2)
        stream = MagicMock()

        class _SD:
            default = SimpleNamespace(device=(0, 0))

            @staticmethod
            def query_devices(index=None):
                devices = [
                    {
                        "name": "hw:0,0",
                        "max_input_channels": 2,
                        "default_samplerate": 48000.0,
                    }
                ]
                return devices if index is None else devices[index]

            @staticmethod
            def check_input_settings(**_kwargs):
                # Only 48 kHz works — forces resample path.
                if _kwargs.get("samplerate") != 48000:
                    raise RuntimeError("bad rate")

            @staticmethod
            def InputStream(**kwargs):
                assert kwargs["device"] == 0
                assert kwargs["samplerate"] == 48000
                stream.callback = kwargs["callback"]
                return stream

        with patch.dict("sys.modules", {"sounddevice": _SD}):
            with patch("dictate.audio.create_preprocessor", return_value=None):
                recorder.start(on_samples=seen.append)

        # 48000 samples (~1s) -> 16000 after resample.
        stream.callback(np.ones((48000, 1), dtype=np.float32), 48000, None, None)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].shape[0], 16000)
        recorder.stop()


if __name__ == "__main__":
    unittest.main()
