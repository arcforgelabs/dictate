#!/usr/bin/env python3
"""Render the raster brand icons from their canonical SVG source.

The brand mark is defined once, in ``assets/dictate.svg`` (see the
``dictate-brand-mark-canonical`` note). The PNG that per-user installs ship
(``assets/dictate.png``) must always be *generated from that SVG* — never
hand-drawn or hand-edited — otherwise it silently drifts (wrong smile, wrong
vertical position) and Linux launcher icons look malformed next to the .deb.

Run this whenever ``assets/dictate.svg`` changes:

    python scripts/render_brand_icons.py

``tests/test_brand_icon.py`` enforces that the committed PNG stays centered and
consistent with the SVG, so a drifted or stale PNG fails CI.

Requires ``cairosvg`` (and its system cairo libs) plus ``pillow``:

    pip install -e ".[dev]"
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 256
# (svg source, png target) pairs rendered 1:1 at SIZE x SIZE.
TARGETS = [("dictate.svg", "dictate.png")]


def render() -> int:
    import cairosvg

    for svg_name, png_name in TARGETS:
        svg = ASSETS / svg_name
        png = ASSETS / png_name
        cairosvg.svg2png(
            url=str(svg), write_to=str(png), output_width=SIZE, output_height=SIZE
        )
        print(f"rendered {svg_name} -> {png_name} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(render())
