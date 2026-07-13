"""Tests for Linux host-audio library exclusion in the engine freeze."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


def _load():
    path = Path(__file__).resolve().parents[1] / "packaging" / "host_audio_libs.py"
    spec = importlib.util.spec_from_file_location("dictate_host_audio_libs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_host = _load()
is_host_audio_binary = _host.is_host_audio_binary
filter_pyinstaller_binaries = _host.filter_pyinstaller_binaries
should_exclude_host_audio_libs = _host.should_exclude_host_audio_libs


class HostAudioBinaryTests(unittest.TestCase):
    def test_detects_portaudio_and_asound_sonames(self) -> None:
        for name in (
            "libportaudio.so.2",
            "libportaudio.so",
            "libasound.so.2",
            "libasound-cfbebb71.so.2.0.0",
            "libpulse.so.0",
            "libpulse-simple.so.0",
            "libpulsecommon-15.0.so",
            "_internal/libportaudio.so.2",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_host_audio_binary(name))

    def test_keeps_unrelated_libs(self) -> None:
        for name in (
            "libavcodec.so.62",
            "libtorch.so",
            "libonnxruntime.so",
            "libgcc_s.so.1",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_host_audio_binary(name))

    def test_filter_removes_host_audio_on_linux(self) -> None:
        binaries = [
            ("libportaudio.so.2", "/usr/lib/libportaudio.so.2", "BINARY"),
            ("libavcodec.so.62", "/tmp/libavcodec.so.62", "BINARY"),
            ("libasound-cfbebb71.so.2.0.0", "/tmp/libasound.so", "BINARY"),
            (
                "av.libs/libasound-cfbebb71.so.2.0.0",
                "/tmp/site-packages/av.libs/libasound-cfbebb71.so.2.0.0",
                "DATA",
            ),
            ("nvidia/cublas/lib/libcublas.so.12", "/tmp/nvidia/cublas.so", "BINARY"),
            ("triton/_C.cpython-311.so", "/tmp/triton/_C.so", "BINARY"),
        ]
        kept = filter_pyinstaller_binaries(binaries, exclude_audio=True, exclude_gpu=True)
        self.assertEqual([item[0] for item in kept], ["libavcodec.so.62"])

    def test_filter_noop_when_disabled(self) -> None:
        binaries = [("libportaudio.so.2", "/usr/lib/libportaudio.so.2", "BINARY")]
        kept = filter_pyinstaller_binaries(binaries, exclude_audio=False, exclude_gpu=False)
        self.assertEqual(kept, binaries)

    def test_windows_keeps_host_audio_by_default(self) -> None:
        with patch.object(_host.os, "name", "nt"):
            self.assertFalse(should_exclude_host_audio_libs())
            self.assertFalse(_host.should_exclude_heavy_gpu_runtimes())

    def test_bundle_override_keeps_host_audio(self) -> None:
        with patch.dict(_host.os.environ, {"DICTATE_BUNDLE_HOST_AUDIO": "1"}):
            self.assertFalse(should_exclude_host_audio_libs())

    def test_gpu_bundle_override_keeps_nvidia(self) -> None:
        with patch.dict(_host.os.environ, {"DICTATE_BUNDLE_GPU_LIBS": "1"}):
            self.assertFalse(_host.should_exclude_heavy_gpu_runtimes())


if __name__ == "__main__":
    unittest.main()
