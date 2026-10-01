from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import types
import tomllib
import unittest
from unittest.mock import patch
from pathlib import Path

from dictate.stt import (
    BACKEND_REGISTRY,
    COMPUTE_TYPES,
    STT_BACKENDS,
    check_backend_readiness,
    create_speech_to_text,
    resolve_model_name,
    saved_compute_type,
)


class SttRegistryTests(unittest.TestCase):
    def test_backend_registry_has_expected_backends(self) -> None:
        self.assertEqual(
            STT_BACKENDS,
            (
                "parakeet",
                "parakeet-pyannote",
                "parakeet-diarizen",
                "parakeet-sortformer",
            ),
        )
        self.assertEqual(tuple(BACKEND_REGISTRY.keys()), STT_BACKENDS)

    def test_compute_types_are_cpu_only(self) -> None:
        self.assertEqual(COMPUTE_TYPES, ("int8", "float32"))

    def test_saved_gpu_only_compute_type_loads_as_int8(self) -> None:
        self.assertEqual(saved_compute_type("float32"), "float32")
        self.assertEqual(saved_compute_type("int8"), "int8")
        self.assertEqual(saved_compute_type("float16"), "int8")
        self.assertEqual(saved_compute_type(None), "int8")
        self.assertEqual(saved_compute_type("bogus"), "int8")

    def test_engine_takes_no_device(self) -> None:
        with self.assertRaises(TypeError):
            create_speech_to_text(backend="parakeet", device="cpu")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            check_backend_readiness(  # type: ignore[call-arg]
                backend="parakeet", model=None, device="cpu"
            )

    def test_resolve_model_name_defaults(self) -> None:
        self.assertEqual(resolve_model_name("parakeet-pyannote", None), "parakeet-tdt-0.6b-v2")
        self.assertEqual(resolve_model_name("parakeet-diarizen", None), "parakeet-tdt-0.6b-v2")
        self.assertEqual(resolve_model_name("parakeet-sortformer", None), "parakeet-tdt-0.6b-v2")
        self.assertEqual(resolve_model_name("parakeet", None), "parakeet-tdt-0.6b-v2")

    def test_create_backend_instances_without_loading_models(self) -> None:
        parakeet = create_speech_to_text(
            backend="parakeet",
            model="parakeet-tdt-0.6b-v2",
        )
        parakeet_pyannote = create_speech_to_text(
            backend="parakeet-pyannote",
            model="parakeet-tdt-0.6b-v2",
        )
        parakeet_diarizen = create_speech_to_text(
            backend="parakeet-diarizen",
            model="parakeet-tdt-0.6b-v2",
        )
        parakeet_sortformer = create_speech_to_text(
            backend="parakeet-sortformer",
            model="parakeet-tdt-0.6b-v2",
        )
        self.assertEqual(parakeet.backend_name, "parakeet")
        self.assertEqual(parakeet_pyannote.backend_name, "parakeet-pyannote")
        self.assertEqual(parakeet_diarizen.backend_name, "parakeet-diarizen")
        self.assertEqual(parakeet_sortformer.backend_name, "parakeet-sortformer")

    @unittest.skipIf(
        sys.platform == "win32",
        "Windows CI intermittently interrupts this subprocess-only import isolation check.",
    )
    def test_registry_import_does_not_require_whisper_runtime(self) -> None:
        code = textwrap.dedent(
            """
            import builtins

            original_import = builtins.__import__
            blocked = ("faster_whisper", "whisperx", "ctranslate2", "av")

            def blocked_import(name, *args, **kwargs):
                if name.split(".")[0] in blocked:
                    raise ModuleNotFoundError(f"removed Whisper runtime: {name}")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = blocked_import

            from dictate.stt import STT_BACKENDS, create_speech_to_text

            assert "parakeet" in STT_BACKENDS
            stt = create_speech_to_text(
                backend="parakeet", model="parakeet-tdt-0.6b-v2"
            )
            assert stt.backend_name == "parakeet"
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)

    def test_backend_readiness_returns_metadata(self) -> None:
        report = check_backend_readiness(
            backend="parakeet",
            model="parakeet-tdt-0.6b-v2",
        )
        self.assertTrue(any(note.startswith("STT backend:") for note in report.notes))
        self.assertTrue(any(note.startswith("STT model:") for note in report.notes))

    def test_readiness_ignores_accelerator_providers(self) -> None:
        # CPU only: readiness never inspects or reports accelerator providers,
        # whatever onnxruntime build happens to be installed.
        fake_ort = types.SimpleNamespace(
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        for backend in ("parakeet", "parakeet-pyannote"):
            with (
                patch("dictate.stt.factory.parakeet_available", return_value=True),
                patch("dictate.stt.factory.pyannote_available", return_value=True),
                patch("dictate.stt.factory.pyannote_token", return_value="token"),
                patch("dictate.stt.factory.pyannote_model_source", return_value="remote/model"),
                patch.dict("sys.modules", {"onnxruntime": fake_ort}),
            ):
                report = check_backend_readiness(backend=backend, model="parakeet-tdt-0.6b-v2")
            self.assertFalse(report.errors, backend)
            self.assertFalse(report.warnings, backend)
            self.assertFalse(
                any("ExecutionProvider" in note for note in report.notes),
                backend,
            )

    def test_pyproject_exposes_windows_amd_extra(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        amd_deps = pyproject["project"]["optional-dependencies"]["amd"]
        self.assertTrue(any("onnxruntime-directml" in dependency for dependency in amd_deps))
        self.assertTrue(any("platform_machine == 'AMD64'" in dependency for dependency in amd_deps))

    def test_pyproject_exposes_meeting_extra_for_pyannote_lane(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        meeting_deps = pyproject["project"]["optional-dependencies"]["meeting"]
        self.assertTrue(any("pyannote.audio" in dependency for dependency in meeting_deps))
        self.assertTrue(any("torch" in dependency for dependency in meeting_deps))

    def test_pyproject_ships_no_whisper_backends(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        deps = [*project["dependencies"]]
        for extra in project["optional-dependencies"].values():
            deps.extend(extra)
        self.assertFalse(any("whisper" in dependency.lower() for dependency in deps))
        self.assertNotIn("whisperx", project["optional-dependencies"])
        # Parakeet's model download used to arrive transitively via faster-whisper.
        self.assertTrue(any(dep.startswith("huggingface-hub") for dep in project["dependencies"]))

    def test_parakeet_pyannote_readiness_reports_missing_optional_package(self) -> None:
        with (
            patch("dictate.stt.factory.parakeet_available", return_value=True),
            patch("dictate.stt.factory.pyannote_available", return_value=False),
        ):
            report = check_backend_readiness(
                backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
            )
        self.assertTrue(any("pyannote.audio is not importable" in error for error in report.errors))

    def test_parakeet_pyannote_readiness_errors_for_missing_token(self) -> None:
        with (
            patch("dictate.stt.factory.parakeet_available", return_value=True),
            patch("dictate.stt.factory.pyannote_available", return_value=True),
            patch("dictate.stt.factory.pyannote_token", return_value=None),
            patch("dictate.stt.factory.pyannote_model_source", return_value="remote/model"),
        ):
            report = check_backend_readiness(
                backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
            )
        self.assertTrue(any("is gated" in error for error in report.errors))

    def test_parakeet_pyannote_readiness_accepts_local_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("dictate.stt.factory.parakeet_available", return_value=True),
                patch("dictate.stt.factory.pyannote_available", return_value=True),
                patch("dictate.stt.factory.pyannote_token", return_value=None),
                patch("dictate.stt.factory.pyannote_model_source", return_value=temp_dir),
            ):
                report = check_backend_readiness(
                    backend="parakeet-pyannote",
                    model="parakeet-tdt-0.6b-v2",
                )
        self.assertFalse(report.errors)
        self.assertTrue(any("pyannote model path" in note for note in report.notes))

    def test_parakeet_diarizen_readiness_reports_missing_optional_runtime(self) -> None:
        with (
            patch("dictate.stt.factory.parakeet_available", return_value=True),
            patch("dictate.stt.factory.diarizen_available", return_value=False),
        ):
            report = check_backend_readiness(
                backend="parakeet-diarizen",
                model="parakeet-tdt-0.6b-v2",
            )
        self.assertTrue(any("DiariZen Meeting backend" in error for error in report.errors))
        self.assertTrue(any("DiariZen model" in note for note in report.notes))

    def test_parakeet_sortformer_readiness_reports_missing_optional_runtime(self) -> None:
        with (
            patch("dictate.stt.factory.parakeet_available", return_value=True),
            patch("dictate.stt.factory.sortformer_available", return_value=False),
        ):
            report = check_backend_readiness(
                backend="parakeet-sortformer",
                model="parakeet-tdt-0.6b-v2",
            )
        self.assertTrue(any("Sortformer Meeting backend" in error for error in report.errors))
        self.assertTrue(any("Sortformer model" in note for note in report.notes))



if __name__ == "__main__":
    unittest.main()
