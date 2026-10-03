from __future__ import annotations

import subprocess
import sys
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
        self.assertEqual(STT_BACKENDS, ("parakeet",))
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
        self.assertEqual(resolve_model_name("parakeet", None), "parakeet-tdt-0.6b-v2")

    def test_create_backend_instances_without_loading_models(self) -> None:
        parakeet = create_speech_to_text(
            backend="parakeet",
            model="parakeet-tdt-0.6b-v2",
        )
        self.assertEqual(parakeet.backend_name, "parakeet")

    @unittest.skipIf(
        sys.platform == "win32",
        "Windows CI intermittently interrupts this subprocess-only import isolation check.",
    )
    def test_registry_import_does_not_require_whisper_or_meeting_runtime(self) -> None:
        code = textwrap.dedent(
            """
            import builtins

            original_import = builtins.__import__
            blocked = (
                "faster_whisper", "whisperx", "ctranslate2", "av",
                "torch", "torchaudio", "torchcodec", "pyannote",
            )

            def blocked_import(name, *args, **kwargs):
                if name.split(".")[0] in blocked:
                    raise ModuleNotFoundError(f"removed runtime: {name}")
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
        for backend in ("parakeet",):
            with (
                patch("dictate.stt.factory.parakeet_available", return_value=True),
                patch.dict("sys.modules", {"onnxruntime": fake_ort}),
            ):
                report = check_backend_readiness(backend=backend, model="parakeet-tdt-0.6b-v2")
            self.assertFalse(report.errors, backend)
            self.assertFalse(report.warnings, backend)
            self.assertFalse(
                any("ExecutionProvider" in note for note in report.notes),
                backend,
            )

    def test_pyproject_ships_no_gpu_runtime(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        self.assertNotIn("gpu", project["optional-dependencies"])
        self.assertNotIn("amd", project["optional-dependencies"])
        dependencies = [*project["dependencies"], *sum(project["optional-dependencies"].values(), [])]
        for dependency in dependencies:
            self.assertNotIn("onnxruntime-gpu", dependency)
            self.assertNotIn("onnxruntime-directml", dependency)

    def test_pyproject_ships_no_meeting_runtime(self) -> None:
        # Meeting capture was removed (#140): no release carries torch or pyannote.
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        for extra in ("meeting", "sortformer", "whisperx"):
            self.assertNotIn(extra, project["optional-dependencies"])
        deps = [*project["dependencies"], *sum(project["optional-dependencies"].values(), [])]
        for name in ("torch", "pyannote", "nemo", "diarizen"):
            self.assertFalse(any(name in dep.lower() for dep in deps), name)

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



if __name__ == "__main__":
    unittest.main()
