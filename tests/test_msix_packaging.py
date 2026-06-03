from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MsixPackagingTests(unittest.TestCase):
    def test_manifest_matches_reserved_partner_center_identity(self) -> None:
        manifest = ROOT / "packaging" / "msix" / "Package.appxmanifest.in"
        tree = ET.parse(manifest)
        root = tree.getroot()
        ns = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}

        identity = root.find("m:Identity", ns)
        self.assertIsNotNone(identity)
        assert identity is not None

        self.assertEqual(identity.attrib["Name"], "ArcForgeLabs.ArcForgeDictate")
        self.assertEqual(
            identity.attrib["Publisher"],
            "CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C",
        )
        self.assertEqual(identity.attrib["Version"], "{{VERSION}}")
        self.assertEqual(identity.attrib["ProcessorArchitecture"], "x64")

        capabilities = {
            node.attrib["Name"]
            for node in root.findall(".//{*}Capability")
            if "Name" in node.attrib
        }
        device_capabilities = {
            node.attrib["Name"]
            for node in root.findall(".//{*}DeviceCapability")
            if "Name" in node.attrib
        }
        self.assertIn("runFullTrust", capabilities)
        self.assertIn("internetClient", capabilities)
        self.assertIn("microphone", device_capabilities)

    def test_msix_builder_uses_store_product_identity_and_makeappx(self) -> None:
        script = (ROOT / "scripts" / "build-windows-msix-store.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("9P5S7747V0BP", script)
        self.assertIn("Package.appxmanifest.in", script)
        self.assertIn("dictate-ui-shell.exe", script)
        self.assertIn("dictate-engine.exe", script)
        self.assertIn("winapp tool makeappx pack", script)
        self.assertRegex(script, re.compile(r"build --no-bundle"))


if __name__ == "__main__":
    unittest.main()
