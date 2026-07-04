"""P2-1: single hardware-aware default local-model resolver."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from dictate.stt import factory as stt_factory
from dictate.stt.factory import resolve_default_local_model


class ResolveDefaultLocalModelTests(unittest.TestCase):
    def test_cuda_available_auto_returns_turbo(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=True):
            self.assertEqual(resolve_default_local_model("auto"), "turbo")

    def test_explicit_cuda_returns_turbo_without_probing(self) -> None:
        # device=="cuda" is an explicit request — no CUDA probe, no RAM heuristic.
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper") as cuda_probe:
            self.assertEqual(resolve_default_local_model("cuda"), "turbo")
            cuda_probe.assert_not_called()

    def test_capable_cpu_returns_turbo(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=16 * 1024**3), \
             patch("os.cpu_count", return_value=12):
            self.assertEqual(resolve_default_local_model("cpu"), "turbo")

    def test_low_ram_cpu_returns_small(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=4 * 1024**3), \
             patch("os.cpu_count", return_value=12):
            self.assertEqual(resolve_default_local_model("cpu"), "small")

    def test_few_cores_cpu_returns_small(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=16 * 1024**3), \
             patch("os.cpu_count", return_value=4):
            self.assertEqual(resolve_default_local_model("cpu"), "small")

    def test_auto_without_cuda_uses_cpu_heuristic(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=16 * 1024**3), \
             patch("os.cpu_count", return_value=12):
            self.assertEqual(resolve_default_local_model("auto"), "turbo")

    def test_unknown_ram_falls_back_to_cpu_count_only(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=None):
            with patch("os.cpu_count", return_value=12):
                self.assertEqual(resolve_default_local_model("cpu"), "turbo")
            with patch("os.cpu_count", return_value=4):
                self.assertEqual(resolve_default_local_model("cpu"), "small")

    def test_unknown_ram_and_cpu_is_conservative(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=None), \
             patch("os.cpu_count", return_value=None):
            self.assertEqual(resolve_default_local_model("cpu"), "small")

    def test_env_override_wins(self) -> None:
        with patch.dict("os.environ", {"DICTATE_FORCE_LOCAL_MODEL": "medium"}):
            # Override wins even where the heuristic would say turbo.
            with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=True):
                self.assertEqual(resolve_default_local_model("auto"), "medium")


if __name__ == "__main__":
    unittest.main()


class ResolveDefaultLocalBackendTests(unittest.TestCase):
    def test_cpu_prefers_parakeet_when_available(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "parakeet_available", return_value=True):
            self.assertEqual(
                stt_factory.resolve_default_local_backend("cpu"),
                ("parakeet", "parakeet-tdt-0.6b-v2"),
            )

    def test_cpu_falls_back_to_whisper_without_parakeet(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=False), \
             patch.object(stt_factory, "parakeet_available", return_value=False), \
             patch.object(stt_factory, "_total_system_ram_bytes", return_value=16 * 1024**3), \
             patch("os.cpu_count", return_value=12):
            backend, model = stt_factory.resolve_default_local_backend("cpu")
            self.assertEqual(backend, "faster-whisper")
            self.assertEqual(model, "turbo")

    def test_cuda_defaults_to_whisper_turbo(self) -> None:
        with patch.object(stt_factory, "_cuda_available_for_faster_whisper", return_value=True):
            self.assertEqual(stt_factory.resolve_default_local_backend("cuda"), ("faster-whisper", "turbo"))

    def test_env_override(self) -> None:
        import os
        orig = os.environ.get("DICTATE_FORCE_LOCAL_BACKEND")
        os.environ["DICTATE_FORCE_LOCAL_BACKEND"] = "faster-whisper"
        try:
            self.assertEqual(stt_factory.resolve_default_local_backend("cpu")[0], "faster-whisper")
        finally:
            if orig is None:
                os.environ.pop("DICTATE_FORCE_LOCAL_BACKEND", None)
            else:
                os.environ["DICTATE_FORCE_LOCAL_BACKEND"] = orig
