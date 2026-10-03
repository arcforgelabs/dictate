from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    child_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=120,
    )


def _onnx_model_tools_installed() -> bool:
    return _run("import onnx, onnxruntime").returncode == 0


class ThirdPartyTelemetryTests(unittest.TestCase):
    def test_importing_dictate_disables_hf_and_onnxruntime_telemetry(self) -> None:
        # A shell that opted in must not switch it back on inside Dictate.
        result = _run(
            """
            import os
            import dictate
            print(
                os.environ["HF_HUB_DISABLE_TELEMETRY"],
                os.environ["ORT_DISABLE_TELEMETRY"],
            )
            """,
            HF_HUB_DISABLE_TELEMETRY="0",
            ORT_DISABLE_TELEMETRY="0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["1", "1"])

    @unittest.skipUnless(_onnx_model_tools_installed(), "onnx and onnxruntime not installed")
    def test_onnxruntime_keeps_no_telemetry_store_once_dictate_is_loaded(self) -> None:
        # Without the opt-out, creating a session writes a device ID and a 1DS
        # event queue under ~/.cache/Microsoft/DeveloperTools and uploads them to
        # mobile.events.data.microsoft.com.
        with tempfile.TemporaryDirectory() as home:
            result = _run(
                """
                import os
                import dictate  # sets the opt-outs before onnxruntime loads
                import numpy as np
                import onnx
                import onnxruntime as ort
                from onnx import TensorProto, helper

                node = helper.make_node("Identity", ["x"], ["y"])
                graph = helper.make_graph(
                    [node],
                    "g",
                    [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
                    [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
                )
                # Pin the IR version: a newer onnx stamps one onnxruntime 1.30 rejects.
                model = helper.make_model(
                    graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=10
                )
                session = ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])
                session.run(None, {"x": np.zeros(1, dtype=np.float32)})
                print(sorted(os.listdir(os.path.expanduser("~/.cache"))) if os.path.isdir(os.path.expanduser("~/.cache")) else [])
                """,
                HOME=home,
                XDG_CACHE_HOME=os.path.join(home, ".cache"),
                ORT_DISABLE_TELEMETRY="0",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Microsoft", result.stdout)
            self.assertFalse(os.path.exists(os.path.join(home, ".cache", "Microsoft", "DeveloperTools")))


if __name__ == "__main__":
    unittest.main()
