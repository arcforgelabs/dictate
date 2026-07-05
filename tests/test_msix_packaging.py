from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from dictate.version import RELEASE_VERSION


ROOT = Path(__file__).resolve().parents[1]


def msi_safe_version(public_version: str) -> str:
    date_part, separator, sequence = public_version.partition("-")
    year, month, day = [int(part) for part in date_part.split(".")]
    patch_sequence = int(sequence) if separator else 0
    return f"{year - 2000}.{month}.{day}.{patch_sequence}"


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

        capabilities_node = root.find("m:Capabilities", ns)
        self.assertIsNotNone(capabilities_node)
        assert capabilities_node is not None
        child_names = [child.tag.rsplit("}", 1)[-1] for child in capabilities_node]
        first_device = child_names.index("DeviceCapability")
        self.assertNotIn("Capability", child_names[first_device + 1 :])

    def test_msix_builder_uses_store_product_identity_and_makeappx(self) -> None:
        script = (ROOT / "scripts" / "build-windows-msix-store.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("9P5S7747V0BP", script)
        self.assertIn("Package.appxmanifest.in", script)
        self.assertIn('Join-Path $Dist "AppxManifest.xml"', script)
        self.assertIn("dictate-ui-shell.exe", script)
        self.assertIn("dictate-engine.exe", script)
        self.assertIn('Kind = "winapp"', script)
        self.assertIn("tool makeappx @Arguments", script)
        self.assertIn('"pack", "/d", $Dist, "/p", $Output, "/o"', script)
        self.assertIn("Windows SDK MakeAppx", script)
        self.assertIn("Invoke-MakeAppx", script)
        self.assertIn("Assert-MsixPackage", script)
        self.assertIn("unpack", script)
        self.assertIn("ArcForgeLabs.ArcForgeDictate", script)
        self.assertIn("building shared Windows desktop payload", script)
        self.assertIn("build-windows-desktop.ps1", script)
        self.assertIn('-Bundles "no-bundle"', script)
        self.assertIn(r"target\release\dictate-ui-shell.exe", script)
        self.assertIn(r"target\release\engine\dictate-engine.exe", script)

    def test_windows_msi_uses_installer_safe_version(self) -> None:
        config = json.loads((ROOT / "ui-shell" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        ))

        app_version = config["version"]
        wix_version = config["bundle"]["windows"]["wix"]["version"]
        self.assertEqual(app_version, RELEASE_VERSION)
        self.assertEqual(wix_version, msi_safe_version(app_version))
        date_part = RELEASE_VERSION.partition("-")[0]
        year, month, day = [int(part) for part in date_part.split(".")]
        self.assertEqual(msi_safe_version(f"{date_part}-1"), f"{year - 2000}.{month}.{day}.1")

        parts = [int(part) for part in wix_version.split(".")]
        self.assertLessEqual(parts[0], 255)
        self.assertLessEqual(parts[1], 255)
        for part in parts[2:]:
            self.assertLessEqual(part, 65535)


if __name__ == "__main__":
    unittest.main()
