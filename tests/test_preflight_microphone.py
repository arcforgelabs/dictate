from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from dictate.preflight import PreflightReport, _check_microphone


def _fake_sounddevice(devices, *, capture_error: Exception | None = None):
    sd = types.ModuleType("sounddevice")
    sd.query_devices = lambda device=None: devices if device is None else devices[device]
    sd.default = types.SimpleNamespace(device=(0 if devices else -1, 0))
    return sd, capture_error


class MicrophonePreflightTests(unittest.TestCase):
    """A missing microphone must not stop the engine from starting."""

    def _run(self, devices, capture_error=None) -> PreflightReport:
        sd, error = _fake_sounddevice(devices, capture_error=capture_error)

        def resolve(_sd):
            if error is not None:
                raise error
            return 0, 16000

        report = PreflightReport()
        with patch.dict(sys.modules, {"sounddevice": sd}), patch(
            "dictate.audio.resolve_input_capture", side_effect=resolve
        ):
            _check_microphone(report)
        return report

    def test_no_input_devices_is_a_warning(self) -> None:
        report = self._run([], capture_error=RuntimeError("no microphone input devices detected"))
        self.assertEqual(report.errors, [])
        self.assertTrue(any("No microphone input devices" in w for w in report.warnings))
        self.assertTrue(any("Could not open microphone input" in w for w in report.warnings))

    def test_working_microphone_has_no_warnings_or_errors(self) -> None:
        report = self._run([{"name": "Mic", "max_input_channels": 1}])
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertTrue(any("Mic" in note for note in report.notes))


if __name__ == "__main__":
    unittest.main()
