from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import numpy as np

from dictate import __main__ as main_module
from dictate.config import Config
from dictate.stt import SttCapabilities


class FakeOnceStt:
    backend_name = "fake"
    model_name = "fake-model"
    capabilities = SttCapabilities(supports_language_hint=True)

    def __init__(self) -> None:
        self.released = False

    @property
    def model(self):
        return object()

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        return "hello"

    def release(self) -> None:
        self.released = True


class MainSttSelectionTests(unittest.TestCase):
    def test_saved_selection_used_when_cli_does_not_override(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="nemo-canary", stt_model="nvidia/canary-1b-v2"),
            )

        self.assertEqual(backend, "nemo-canary")
        self.assertEqual(model, "nvidia/canary-1b-v2")

    def test_cli_flags_override_saved_selection(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--stt-backend", "faster-whisper", "--model", "small"])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=["--stt-backend", "faster-whisper", "--model", "small"],
                config=Config(stt_backend="nemo-canary", stt_model="nvidia/canary-1b-v2"),
            )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "small")

    def test_invalid_saved_backend_falls_back_to_cli_defaults(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "_cuda_available_for_faster_whisper", return_value=False):
            with contextlib.redirect_stderr(io.StringIO()):
                backend, model = main_module._resolve_startup_stt(
                    args=args,
                    cli_args=[],
                    config=Config(stt_backend="not-a-backend", stt_model="x"),
                )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "base")

    def test_default_startup_stt_prefers_turbo_when_cuda_is_available(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "_cuda_available_for_faster_whisper", return_value=True):
            with contextlib.redirect_stderr(io.StringIO()):
                backend, model = main_module._resolve_startup_stt(
                    args=args,
                    cli_args=[],
                    config=Config(),
                )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "turbo")

    def test_default_startup_stt_prefers_base_when_cuda_is_unavailable(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "_cuda_available_for_faster_whisper", return_value=False):
            with contextlib.redirect_stderr(io.StringIO()):
                backend, model = main_module._resolve_startup_stt(
                    args=args,
                    cli_args=[],
                    config=Config(),
                )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "base")

    def test_saved_backend_without_model_uses_auto_recommended_model(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "_cuda_available_for_faster_whisper", return_value=True):
            with contextlib.redirect_stderr(io.StringIO()):
                backend, model = main_module._resolve_startup_stt(
                    args=args,
                    cli_args=[],
                    config=Config(stt_backend="faster-whisper"),
                )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "turbo")

    def test_whisper_cpp_backend_without_model_uses_local_turbo_default(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="whisper-cpp"),
            )

        self.assertEqual(backend, "whisper-cpp")
        self.assertEqual(model, "large-v3-turbo-q5_0")

    def test_saved_runtime_profile_used_when_cli_does_not_override(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            device, compute_type = main_module._resolve_startup_runtime(
                args=args,
                cli_args=[],
                config=Config(stt_device="cuda", stt_compute_type="float16"),
            )

        self.assertEqual(device, "cuda")
        self.assertEqual(compute_type, "float16")

    def test_cli_runtime_flags_override_saved_profile(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--device", "cpu", "--compute-type", "float32"])

        with contextlib.redirect_stderr(io.StringIO()):
            device, compute_type = main_module._resolve_startup_runtime(
                args=args,
                cli_args=["--device", "cpu", "--compute-type", "float32"],
                config=Config(stt_device="cuda", stt_compute_type="float16"),
            )

        self.assertEqual(device, "cpu")
        self.assertEqual(compute_type, "float32")

    def test_invalid_saved_runtime_profile_falls_back_to_cli_defaults(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            device, compute_type = main_module._resolve_startup_runtime(
                args=args,
                cli_args=[],
                config=Config(stt_device="bad-device", stt_compute_type="bad-compute"),
            )

        self.assertEqual(device, "auto")
        self.assertEqual(compute_type, "int8")

    def test_run_once_releases_stt_resources(self) -> None:
        stt = FakeOnceStt()
        output = Mock()

        with patch("dictate.audio.SoundDeviceRecorder"):
            with patch(
                "dictate.__main__.record_until_enter",
                return_value=np.ones(16000, dtype=np.float32),
            ):
                with patch("dictate.__main__.StdoutOutput", return_value=output):
                    main_module._run_once(
                        stt,
                        copy_to_clipboard=False,
                        language=None,
                        hotwords=None,
                        lexicon_mode="native",
                        lexicon_replacements=None,
                    )

        self.assertTrue(stt.released)

    def test_saved_lexicon_mode_used_when_cli_does_not_override(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            lexicon_mode = main_module._resolve_startup_lexicon_mode(
                args=args,
                cli_args=[],
                config=Config(lexicon_mode="hybrid"),
            )

        self.assertEqual(lexicon_mode, "hybrid")

    def test_cli_lexicon_mode_overrides_saved_mode(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--lexicon-mode", "post"])

        with contextlib.redirect_stderr(io.StringIO()):
            lexicon_mode = main_module._resolve_startup_lexicon_mode(
                args=args,
                cli_args=["--lexicon-mode", "post"],
                config=Config(lexicon_mode="hybrid"),
            )

        self.assertEqual(lexicon_mode, "post")

    def test_saved_push_to_talk_combo_used_when_cli_does_not_override(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            hotkey = main_module._resolve_startup_push_to_talk_combo(
                args=args,
                cli_args=[],
                config=Config(push_to_talk_combo="ctrl+space"),
            )

        self.assertEqual(hotkey, "ctrl+space")

    def test_legacy_saved_push_to_talk_key_is_still_honored(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            hotkey = main_module._resolve_startup_push_to_talk_combo(
                args=args,
                cli_args=[],
                config=Config(push_to_talk_key="ctrl_l"),
            )

        self.assertEqual(hotkey, "ctrl_l")

    def test_cli_push_to_talk_combo_overrides_saved_value(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--push-to-talk-combo", "ctrl+space"])

        with contextlib.redirect_stderr(io.StringIO()):
            hotkey = main_module._resolve_startup_push_to_talk_combo(
                args=args,
                cli_args=["--push-to-talk-combo", "ctrl+space"],
                config=Config(push_to_talk_combo="ctrl_l"),
            )

        self.assertEqual(hotkey, "ctrl+space")

    def test_wayland_default_push_to_talk_combo_prefers_ctrl_space(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "detect_session_type", return_value="wayland"):
            with contextlib.redirect_stderr(io.StringIO()):
                hotkey = main_module._resolve_startup_push_to_talk_combo(
                    args=args,
                    cli_args=[],
                    config=Config(),
                )

        self.assertEqual(hotkey, "ctrl+space")

    def test_x11_default_push_to_talk_combo_stays_right_ctrl(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "detect_session_type", return_value="x11"):
            with contextlib.redirect_stderr(io.StringIO()):
                hotkey = main_module._resolve_startup_push_to_talk_combo(
                    args=args,
                    cli_args=[],
                    config=Config(),
                )

        self.assertEqual(hotkey, "ctrl_r")


if __name__ == "__main__":
    unittest.main()
