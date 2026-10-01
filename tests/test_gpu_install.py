from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _gpu_extra_bounds() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (requirement,) = pyproject["project"]["optional-dependencies"]["gpu"]
    match = re.search(r"onnxruntime-gpu\[[^\]]*\](>=[^;\s\"]+)", requirement)
    assert match, requirement
    return match.group(1)


class GpuInstallTests(unittest.TestCase):
    """onnxruntime and onnxruntime-gpu share one package directory.

    A plain install of the gpu extra leaves the CPU build's files in place, so
    the installers must remove the CPU build and rewrite the GPU build's files.
    """

    def test_linux_installer_replaces_cpu_onnxruntime_when_gpu_is_selected(self) -> None:
        script = (ROOT / "install.sh").read_text(encoding="utf-8")
        gpu_block = script[script.index('if [ "$INSTALL_GPU" -eq 1 ]; then\n  # onnxruntime'):]
        self.assertIn("uv pip uninstall onnxruntime", gpu_block)
        self.assertIn("--reinstall-package onnxruntime-gpu --no-deps", gpu_block)
        self.assertIn(f'ONNXRUNTIME_GPU_SPEC="onnxruntime-gpu{_gpu_extra_bounds()}"', script)

    def test_windows_installer_forces_the_gpu_files_back(self) -> None:
        script = (ROOT / "install-windows.ps1").read_text(encoding="utf-8")
        function = script[script.index("function Ensure-OnnxCudaRuntime"):]
        function = function[: function.index("\n}\n")]
        uninstall = function.index('"uninstall", "-y", "onnxruntime"')
        reinstall = function.index('"--force-reinstall", "--no-deps"')
        self.assertLess(uninstall, reinstall)
        bounds = _gpu_extra_bounds()
        self.assertIn(f'"onnxruntime-gpu[cuda,cudnn]{bounds}"', function)
        self.assertIn(f'"onnxruntime-gpu{bounds}"', function)


if __name__ == "__main__":
    unittest.main()
