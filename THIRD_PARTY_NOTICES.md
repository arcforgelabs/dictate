# Third-party notices

Dictate is released under the MIT License (`LICENSE`). The desktop app bundles
the open-source libraries and models below, each under its own licence. Full
texts of the GNU licences named here are in `licenses/` beside this file in an
installed app, and in `packaging/notices/licenses/` in the source repository.

Source for Dictate, and the build scripts that produce every release
(`packaging/build-engine.sh`, `scripts/build-windows-desktop.ps1`), is at
<https://github.com/arcforgelabs/dictate>.

## Models

The model runs on the device and is redistributed unmodified. Its directory in
the app carries an `ATTRIBUTION.md`.

| Model | By | Licence |
| --- | --- | --- |
| Parakeet TDT 0.6B v2, ONNX int8 conversion `istupakov/parakeet-tdt-0.6b-v2-onnx` of `nvidia/parakeet-tdt-0.6b-v2` | NVIDIA (conversion: istupakov) | CC BY 4.0 |

CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>

## Copyleft components

These are shipped as separate, replaceable files or Python modules. Dictate's own
code is MIT and fully published, so you can rebuild the app against a modified
version of any of them with the build scripts above. Their source is available
from the upstream projects linked.

| Component | Licence | Where | Source |
| --- | --- | --- | --- |
| pynput | LGPL-3.0 | Hotkeys and typing, Linux X11 and Windows | <https://github.com/moses-palmer/pynput> |
| python-xlib | LGPL-2.1-or-later | Linux X11 | <https://github.com/python-xlib/python-xlib> |
| certifi | MPL-2.0 | TLS root certificates for update checks and model downloads | <https://github.com/certifi/python-certifi> |
| tqdm | MPL-2.0 AND MIT | Progress reporting in model libraries | <https://github.com/tqdm/tqdm> |

## Speech runtime

| Component | Licence | Project |
| --- | --- | --- |
| onnx-asr | MIT | <https://github.com/istupakov/onnx-asr> |
| ONNX Runtime | MIT | <https://github.com/microsoft/onnxruntime> |
| huggingface_hub, hf-xet | Apache-2.0 | <https://github.com/huggingface/huggingface_hub> |
| protobuf (ONNX Runtime) | BSD-3-Clause | <https://github.com/protocolbuffers/protobuf> |

## Core

| Component | Licence | Project |
| --- | --- | --- |
| CPython runtime | PSF-2.0 | <https://www.python.org> |
| PyInstaller bootloader | GPL-2.0 with the PyInstaller bootloader exception, which permits distribution with any application | <https://pyinstaller.org> |
| NumPy | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) | <https://numpy.org> |
| PyYAML | MIT | <https://github.com/yaml/pyyaml> |
| sounddevice | MIT | <https://github.com/spatialaudio/python-sounddevice> |
| webrtc-noise-gain (Linux) | Apache-2.0 | <https://github.com/rhasspy/webrtc-noise-gain> |
| evdev (Linux) | BSD-3-Clause | <https://github.com/gvalkov/python-evdev> |
| charset-normalizer | MIT | <https://github.com/jawah/charset_normalizer> |
| requests, urllib3, idna | Apache-2.0, MIT, BSD-3-Clause | <https://github.com/psf/requests> |
| pyperclip (Windows) | BSD-3-Clause | <https://github.com/asweigart/pyperclip> |
| GCC runtime libraries (libgcc, libstdc++, libgomp, libgfortran, libquadmath) | GPL-3.0 with the GCC Runtime Library Exception | <https://gcc.gnu.org> |

On Linux, Dictate uses the system PortAudio library (MIT), installed as a
package dependency rather than bundled.

## Desktop shell

The window and tray are a Tauri app (MIT OR Apache-2.0,
<https://tauri.app>) with a React interface (MIT, <https://react.dev>). Their
Rust crates and npm packages are under permissive licences (predominantly MIT
and Apache-2.0); the exact set and versions are pinned in
`ui-shell/src-tauri/Cargo.lock`, `ui-shell/package-lock.json` and
`ui/package-lock.json`.

## No endorsement

Project names are listed for attribution. Their authors do not endorse Dictate
or Arc Forge.
