from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build-linux-desktop.sh"


class LinuxPackagingLayoutTests(unittest.TestCase):
    def test_engine_layout_matches_each_requested_bundle_lane(self) -> None:
        cases = (
            ("deb,rpm", ("engine:onedir", "tauri:deb,rpm:unset"), "onedir"),
            ("appimage", ("engine:onefile", "tauri:appimage:1"), "onefile"),
            (
                "deb,appimage",
                ("engine:onedir", "tauri:deb:unset", "engine:onefile", "tauri:appimage:1"),
                "onefile",
            ),
        )

        for bundles, expected_events, final_layout in cases:
            with self.subTest(bundles=bundles):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    result, log_path = self._run_build(root, bundles)

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(tuple(log_path.read_text(encoding="utf-8").splitlines()), expected_events)
                    engine = root / "ui-shell" / "src-tauri" / "engine"
                    self.assertTrue((engine / "dictate-engine").is_file())
                    if final_layout == "onedir":
                        self.assertTrue((engine / "_internal").is_dir())
                    else:
                        self.assertFalse((engine / "_internal").exists())

    def _run_build(self, root: Path, bundles: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        (root / "scripts").mkdir(parents=True)
        (root / "packaging" / "dist").mkdir(parents=True)
        (root / "ui").mkdir()
        (root / "ui-shell" / "src-tauri").mkdir(parents=True)
        build_script = root / "scripts" / "build-linux-desktop.sh"
        shutil.copy2(BUILD_SCRIPT, build_script)
        build_script.chmod(0o755)

        stub_bin = root / "stub-bin"
        stub_bin.mkdir()
        log_path = root / "stub.log"
        self._write_executable(stub_bin / "cargo", "#!/usr/bin/env bash\nexit 0\n")
        self._write_executable(
            stub_bin / "pkg-config",
            "#!/usr/bin/env bash\n[[ \"${1:-}\" == \"--exists\" ]]\n",
        )
        self._write_executable(
            stub_bin / "npm",
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"run tauri -- build --bundles"* ]]; then
  args=("$@")
  bundles=""
  for ((i = 0; i < ${#args[@]}; i++)); do
    if [[ "${args[i]}" == "--bundles" ]]; then
      bundles="${args[i + 1]}"
      break
    fi
  done
  printf 'tauri:%s:%s\\n' "$bundles" "${DICTATE_ONEFILE:-unset}" >> "$STUB_LOG"
  IFS=',' read -ra requested <<< "$bundles"
  for bundle in "${requested[@]}"; do
    mkdir -p "src-tauri/target/release/bundle/$bundle"
    case "$bundle" in
      deb) artifact="stub.deb" ;;
      rpm) artifact="stub.rpm" ;;
      appimage) artifact="stub.AppImage" ;;
      *) artifact="stub.$bundle" ;;
    esac
    touch "src-tauri/target/release/bundle/$bundle/$artifact"
  done
fi
""",
        )
        self._write_executable(
            root / "packaging" / "build-engine.sh",
            """#!/usr/bin/env bash
set -euo pipefail
layout=onedir
if [[ "${DICTATE_ONEFILE:-}" == "1" ]]; then layout=onefile; fi
printf 'engine:%s\\n' "$layout" >> "$STUB_LOG"
rm -rf packaging/dist/dictate-engine
if [[ "$layout" == "onefile" ]]; then
  printf '#!/usr/bin/env bash\\n' > packaging/dist/dictate-engine
else
  mkdir -p packaging/dist/dictate-engine/_internal
  printf '#!/usr/bin/env bash\\n' > packaging/dist/dictate-engine/dictate-engine
fi
""",
        )

        env = os.environ.copy()
        env.update(
            {
                "DICTATE_BUNDLES": bundles,
                "PATH": f"{stub_bin}{os.pathsep}{env['PATH']}",
                "STUB_LOG": str(log_path),
            }
        )
        result = subprocess.run(
            ["bash", str(build_script)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, log_path

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
