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


def _pyannote_installed() -> bool:
    return _run("import pyannote.audio.telemetry.metrics").returncode == 0


class ThirdPartyTelemetryTests(unittest.TestCase):
    def test_importing_dictate_disables_pyannote_and_hf_telemetry(self) -> None:
        # A shell that opted in must not switch it back on inside Dictate.
        result = _run(
            """
            import os
            import dictate
            print(
                os.environ["PYANNOTE_METRICS_ENABLED"],
                os.environ["HF_HUB_DISABLE_TELEMETRY"],
                os.environ["ORT_DISABLE_TELEMETRY"],
            )
            """,
            PYANNOTE_METRICS_ENABLED="true",
            HF_HUB_DISABLE_TELEMETRY="0",
            ORT_DISABLE_TELEMETRY="0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["0", "1", "1"])

    @unittest.skipUnless(_pyannote_installed(), "pyannote.audio (meeting extra) not installed")
    def test_pyannote_exports_no_spans_once_dictate_is_loaded(self) -> None:
        # Count every span pyannote would hand its OTLP exporter for
        # otel.pyannote.ai; none may be produced.
        result = _run(
            """
            import dictate.stt.parakeet_pyannote_backend  # the meeting backend's import path
            from pyannote.audio.telemetry import metrics

            exported = []
            metrics.exporter.export = lambda spans: exported.extend(spans)

            class _Pipeline:
                _otel_origin = "test"
                _otel_name = "test"

            metrics.track_pipeline_init(_Pipeline())
            metrics.track_model_init(_Pipeline())
            metrics.provider.force_flush()
            print(metrics.is_metrics_enabled(), len(exported))
            """,
            PYANNOTE_METRICS_ENABLED="true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["False", "0"])

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
