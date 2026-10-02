from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLED_MODELS = ("parakeet-tdt-0.6b-v2-onnx", "pyannote-speaker-diarization-community-1")


def _stage_module():
    spec = importlib.util.spec_from_file_location("stage_notices", ROOT / "scripts" / "stage-notices.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ThirdPartyNoticesTests(unittest.TestCase):
    def test_notices_attribute_bundled_models_and_copyleft_components(self) -> None:
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for required in (
            "istupakov/parakeet-tdt-0.6b-v2-onnx",
            "nvidia/parakeet-tdt-0.6b-v2",
            "pyannote/speaker-diarization-community-1",
            "CC BY 4.0",
            "pynput | LGPL-3.0",
            "python-xlib | LGPL-2.1-or-later",
        ):
            self.assertIn(required, notices)

    def test_every_bundled_model_has_a_cc_by_attribution(self) -> None:
        for model in BUNDLED_MODELS:
            attribution = ROOT / "packaging" / "notices" / "models" / model / "ATTRIBUTION.md"
            self.assertIn("CC BY 4.0", attribution.read_text(encoding="utf-8"), model)

    def test_gnu_licence_texts_are_shipped(self) -> None:
        licences = ROOT / "packaging" / "notices" / "licenses"
        for name in ("LGPL-2.1.txt", "LGPL-3.0.txt", "GPL-3.0.txt"):
            self.assertIn("GNU", (licences / name).read_text(encoding="utf-8"), name)

    def test_stage_copies_notices_beside_engine_and_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            for model in BUNDLED_MODELS:
                (engine / "models" / model).mkdir(parents=True)

            _stage_module().stage(engine)

            self.assertTrue((engine / "THIRD_PARTY_NOTICES.md").is_file())
            self.assertTrue((engine / "licenses" / "LGPL-3.0.txt").is_file())
            for model in BUNDLED_MODELS:
                self.assertTrue((engine / "models" / model / "ATTRIBUTION.md").is_file(), model)

    def test_stage_refuses_a_missing_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                _stage_module().stage(Path(tmp))

    def test_desktop_builds_stage_notices(self) -> None:
        for script in ("packaging/build-engine.sh", "scripts/build-windows-desktop.ps1"):
            self.assertIn("stage-notices.py", (ROOT / script).read_text(encoding="utf-8"), script)
        msix = (ROOT / "scripts" / "build-windows-msix-store.ps1").read_text(encoding="utf-8")
        self.assertIn("engine\\THIRD_PARTY_NOTICES.md", msix)

    def test_npm_package_ships_notices(self) -> None:
        import json

        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("THIRD_PARTY_NOTICES.md", package["files"])


if __name__ == "__main__":
    unittest.main()
