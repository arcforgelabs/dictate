#!/usr/bin/env python3
"""Render every raster brand asset from its canonical SVG source.

The brand mark is defined once, in ``assets/dictate.svg`` (see the
``dictate-brand-mark-canonical`` note). Every PNG / ICO the app ships — the
per-user Linux launcher icon, the Windows tray icons, the Tauri bundle icons,
the transparent marks, the circular badge, the Store listing logos and the
MSIX manifest logos — must always be *generated from
the SVGs* — never hand-drawn or hand-edited — otherwise they silently drift
(wrong smile, wrong vertical position, pitch-black tile) and look malformed
next to each other.

Run this whenever anything in ``assets/*.svg`` changes:

    python scripts/render_brand_icons.py

``tests/test_brand_icon.py`` enforces that the committed PNG stays centered and
consistent with the SVG, so a drifted or stale PNG fails CI.

Requires ``cairosvg`` (and its system cairo libs) plus ``pillow``:

    pip install -e ".[dev]"
"""

from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TAURI_ICONS = ROOT / "ui-shell" / "src-tauri" / "icons"
STORE_LOGOS = ROOT / "docs" / "msstore" / "assets" / "logos"
MSIX_ASSETS = ROOT / "packaging" / "msix" / "assets"

# MSIX manifest logos, as resource-qualified files that the build indexes into
# resources.pri. The taskbar, Start and title bar draw Square44x44Logo from the
# targetsize-*_altform-unplated variants; without them Windows paints the icon
# on a square accent-coloured plate instead of keeping the tile's transparent
# rounded corners.
MSIX_SCALES = (100, 125, 150, 200, 400)
MSIX_TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)
MSIX_LOGOS = [
    *[(f"StoreLogo.scale-{s}.png", round(50 * s / 100)) for s in MSIX_SCALES],
    *[(f"Square150x150Logo.scale-{s}.png", round(150 * s / 100)) for s in MSIX_SCALES],
    *[(f"Square44x44Logo.scale-{s}.png", round(44 * s / 100)) for s in MSIX_SCALES],
    *[
        (f"Square44x44Logo.targetsize-{t}{altform}.png", t)
        for t in MSIX_TARGET_SIZES
        for altform in ("", "_altform-unplated", "_altform-lightunplated")
    ],
]

# (svg source, png target, size) rendered 1:1.
PNG_TARGETS = [
    (ASSETS / "dictate.svg", ASSETS / "dictate.png", 256),
    (ASSETS / "dictate-listening.svg", ASSETS / "dictate-listening.png", 256),
    (ASSETS / "dictate-mark-ink.svg", ASSETS / "dictate-mark-ink.png", 512),
    (ASSETS / "dictate-mark-bone.svg", ASSETS / "dictate-mark-bone.png", 512),
    (ASSETS / "dictate-badge.svg", ASSETS / "dictate-badge.png", 512),
    (ASSETS / "dictate.svg", TAURI_ICONS / "32x32.png", 32),
    (ASSETS / "dictate.svg", TAURI_ICONS / "128x128.png", 128),
    (ASSETS / "dictate.svg", TAURI_ICONS / "128x128@2x.png", 256),
    (ASSETS / "dictate.svg", TAURI_ICONS / "icon.png", 512),
    # Microsoft Store listing uploads (docs/msstore-listing.md) …
    *[(ASSETS / "dictate.svg", STORE_LOGOS / f"dictate-store-logo-{s}.png", s) for s in (71, 150, 300, 512, 600, 1080, 1240)],
    # … and the MSIX manifest logos (packaging/msix/Package.appxmanifest.in).
    *[(ASSETS / "dictate.svg", MSIX_ASSETS / name, size) for name, size in MSIX_LOGOS],
]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
# (svg source, ico target) — one multi-resolution .ico per source.
ICO_TARGETS = [
    (ASSETS / "dictate.svg", ASSETS / "dictate.ico"),
    (ASSETS / "dictate-listening.svg", ASSETS / "dictate-listening.ico"),
    (ASSETS / "dictate.svg", TAURI_ICONS / "icon.ico"),
]


def _render(svg: Path, size: int):
    import cairosvg
    from PIL import Image

    data = cairosvg.svg2png(url=str(svg), output_width=size, output_height=size)
    # Tauri's generate_context! panics on anything but RGBA.
    return Image.open(io.BytesIO(data)).convert("RGBA")


def render() -> int:
    for svg, png, size in PNG_TARGETS:
        _render(svg, size).save(png)
        print(f"rendered {svg.name} -> {png.relative_to(ROOT)} ({size}x{size})")
    for svg, ico in ICO_TARGETS:
        frames = [_render(svg, s) for s in ICO_SIZES]
        # Pillow writes the ICO from the largest frame, resampling down unless
        # every size is supplied via append_images — so render each size crisp.
        frames[-1].save(
            ico,
            format="ICO",
            sizes=[(s, s) for s in ICO_SIZES],
            append_images=frames[:-1],
        )
        print(f"rendered {svg.name} -> {ico.relative_to(ROOT)} {ICO_SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(render())
