"""Guard that Windows PowerShell bootstrap scripts negotiate TLS 1.2.

Stock Windows 10 / Windows PowerShell 5.1 can default to negotiating TLS 1.0/1.1,
which GitHub and jsdelivr reject, killing the bootstrap on the very first web
request. This is otherwise untestable shell behavior, so we scan the source for
the explicit SecurityProtocol directive instead.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TLS12_DIRECTIVE = (
    "[Net.ServicePointManager]::SecurityProtocol = "
    "[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12"
)

BOOTSTRAP_SCRIPTS = [
    "install.ps1",
    "install-windows.ps1",
    "update.ps1",
    "install-windows-wizard.ps1",
]

# Word-boundary matches, not bare substrings: a loose `in` check on short
# aliases like "iex"/"iwr" risks matching inside an unrelated identifier a
# future edit introduces rather than the actual cmdlet/alias invocation. \b
# anchors this to real tokens instead of arbitrary substrings.
WEB_REQUEST_PATTERN = re.compile(
    r"\b(?:Invoke-WebRequest|Invoke-RestMethod|WebClient|Start-BitsTransfer|iwr|iex)\b"
)


class PowershellTlsBootstrapTests(unittest.TestCase):
    def test_bootstrap_scripts_force_tls12_before_first_web_request(self) -> None:
        for name in BOOTSTRAP_SCRIPTS:
            path = REPO_ROOT / name
            with self.subTest(script=name):
                self.assertTrue(path.is_file(), f"{path} not found")
                source = path.read_text(encoding="ascii")
                self.assertIn(
                    TLS12_DIRECTIVE,
                    source,
                    f"{name} is missing the TLS 1.2 SecurityProtocol directive",
                )

                tls_index = source.index(TLS12_DIRECTIVE)
                first_web_request = WEB_REQUEST_PATTERN.search(source)
                if first_web_request is not None:
                    self.assertLess(
                        tls_index,
                        first_web_request.start(),
                        f"{name} must set TLS 1.2 before its first web request",
                    )

    def test_bootstrap_scripts_stay_bom_free_ascii(self) -> None:
        for name in BOOTSTRAP_SCRIPTS:
            path = REPO_ROOT / name
            with self.subTest(script=name):
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{name} must not have a BOM")
                try:
                    raw.decode("ascii")
                except UnicodeDecodeError as exc:  # pragma: no cover - failure path
                    self.fail(f"{name} contains non-ASCII bytes: {exc}")


if __name__ == "__main__":
    unittest.main()
