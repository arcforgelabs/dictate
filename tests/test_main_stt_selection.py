from __future__ import annotations

import contextlib
import io
import sys
import types
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
                config=Config(stt_backend="gemini", stt_model="gemini-3-flash-preview"),
            )

        self.assertEqual(backend, "gemini")
        self.assertEqual(model, "gemini-3-flash-preview")

    def test_cli_flags_override_saved_selection(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--stt-backend", "faster-whisper", "--model", "small"])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=["--stt-backend", "faster-whisper", "--model", "small"],
                config=Config(stt_backend="gemini", stt_model="gemini-3-flash-preview"),
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
        self.assertEqual(model, "turbo")

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

    def test_default_startup_stt_uses_single_local_turbo_model_without_cuda(self) -> None:
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
        self.assertEqual(model, "turbo")

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

    def test_saved_non_example_model_name_is_preserved(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="faster-whisper", stt_model="base"),
            )

        self.assertEqual(backend, "faster-whisper")
        self.assertEqual(model, "base")

    def test_saved_custom_hosted_model_name_is_preserved(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="gemini", stt_model="gemini-future-model"),
            )

        self.assertEqual(backend, "gemini")
        self.assertEqual(model, "gemini-future-model")

    def test_gemini_backend_without_model_uses_remote_default(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="gemini"),
            )

        self.assertEqual(backend, "gemini")
        self.assertEqual(model, "gemini-3-flash-preview")

    def test_openai_backend_without_model_uses_remote_default(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with contextlib.redirect_stderr(io.StringIO()):
            backend, model = main_module._resolve_startup_stt(
                args=args,
                cli_args=[],
                config=Config(stt_backend="openai"),
            )

        self.assertEqual(backend, "openai")
        self.assertEqual(model, "gpt-4o-mini-transcribe")

    def test_openai_key_command_from_config_is_applied(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            main_module._apply_configured_secret_commands(
                config=Config(
                    stt_backend="openai",
                    openai_api_key_command="/usr/bin/printf key",
                ),
                stt_backend="openai",
            )

            self.assertEqual(
                main_module.os.environ.get("DICTATE_OPENAI_API_KEY_COMMAND"),
                "/usr/bin/printf key",
            )

    def test_xai_key_command_from_config_is_applied(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            main_module._apply_configured_secret_commands(
                config=Config(
                    stt_backend="xai",
                    xai_api_key_command="/usr/bin/printf key",
                ),
                stt_backend="xai",
            )

            self.assertEqual(
                main_module.os.environ.get("DICTATE_XAI_API_KEY_COMMAND"),
                "/usr/bin/printf key",
            )

    def test_gemini_key_command_from_config_is_applied(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            main_module._apply_configured_secret_commands(
                config=Config(
                    stt_backend="gemini",
                    gemini_api_key_command="/usr/bin/printf key",
                ),
                stt_backend="gemini",
            )

            self.assertEqual(
                main_module.os.environ.get("DICTATE_GEMINI_API_KEY_COMMAND"),
                "/usr/bin/printf key",
            )

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

    def test_run_tray_uses_native_windows_tray_on_windows(self) -> None:
        stt = FakeOnceStt()
        output = Mock()
        calls = {}
        fake_windows_tray = types.ModuleType("dictate.windows_tray")

        class FakeWindowsTrayIcon:
            def __init__(self, daemon) -> None:  # noqa: ANN001
                calls["daemon"] = daemon

            def run(self) -> None:
                calls["ran"] = True

        fake_windows_tray.WindowsTrayIcon = FakeWindowsTrayIcon

        with (
            patch.object(main_module.sys, "platform", "win32"),
            patch.object(main_module, "_resolve_typing_output_or_exit", return_value=output),
            patch.dict(sys.modules, {"dictate.windows_tray": fake_windows_tray}),
        ):
            main_module._run_tray(
                stt,
                type_backend="auto",
                language=None,
                hotwords=None,
                lexicon_mode="native",
                lexicon_replacements=None,
                push_to_talk_combo="ctrl_r",
            )

        self.assertTrue(calls["ran"])
        self.assertIs(calls["daemon"].output, output)
        self.assertIs(calls["daemon"].engine.stt, stt)

    def test_daemon_lock_exit_prevents_second_listener(self) -> None:
        with patch("dictate.__main__.ProcessLock") as lock_cls:
            lock_cls.return_value.acquire.return_value = False
            with self.assertRaises(SystemExit) as raised:
                main_module._acquire_daemon_lock_or_exit()

        self.assertEqual(raised.exception.code, 0)

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

    def test_x11_default_push_to_talk_combo_is_ctrl_d(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args([])

        with patch.object(main_module, "detect_session_type", return_value="x11"):
            with contextlib.redirect_stderr(io.StringIO()):
                hotkey = main_module._resolve_startup_push_to_talk_combo(
                    args=args,
                    cli_args=[],
                    config=Config(),
                )

        self.assertEqual(hotkey, "ctrl+d")


if __name__ == "__main__":
    unittest.main()
