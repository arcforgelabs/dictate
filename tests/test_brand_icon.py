"""Guard against the app icon drifting from its canonical SVG.

`assets/dictate.png` is what per-user Linux installs ship as the launcher icon.
It regressed once: it had been produced separately from `assets/dictate.svg`
and drifted — a different smile with round-cap "knobs" and the glyph shoved
~18px up — so the launcher looked malformed next to .deb installs. See
`scripts/render_brand_icons.py` (the canonical generator) and the
`dictate-brand-mark-canonical` note.

Two checks:
- centered: the white glyph must sit centered in the tile (Pillow only, so it
  runs in CI).
- matches SVG: the committed PNG must equal a fresh render of the SVG (needs
  cairosvg; skipped where it is unavailable, e.g. minimal CI images).
"""

from __future__ import annotations

import unittest
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON = ASSETS / "dictate.png"
SVG = ASSETS / "dictate.svg"

try:
    from PIL import Image, ImageChops

    _HAVE_PIL = True
except Exception:  # noqa: BLE001
    _HAVE_PIL = False

try:
    import cairosvg  # noqa: F401

    _HAVE_CAIROSVG = True
except Exception:  # noqa: BLE001
    _HAVE_CAIROSVG = False

# The glyph is white on a near-black (#050505) tile; normalise so the tile maps
# to 0 and the glyph to full coverage while keeping anti-aliased edges.
_LUT = [max(0, min(255, int((v - 5) * 255 / 250))) for v in range(256)]


def _glyph_margins(img):
    """Return (size, top, bottom, left, right) margins of the white glyph."""
    im = img.convert("RGBA")
    size = im.size[0]
    cov = ImageChops.multiply(im.convert("L").point(_LUT), im.split()[3])
    box = cov.point(lambda v: 255 if v > 128 else 0).getbbox()
    left, top, right_excl, bottom_excl = box
    return size, top, size - bottom_excl, left, size - right_excl


@unittest.skipUnless(_HAVE_PIL, "Pillow not available")
class BrandIconCenteringTests(unittest.TestCase):
    def test_icon_glyph_is_centered(self) -> None:
        with Image.open(ICON) as img:
            size, top, bottom, left, right = _glyph_margins(img)
        # Tolerance absorbs anti-aliasing; the historical regression was ~37px off.
        self.assertLessEqual(
            abs(top - bottom), 6, f"icon not vertically centered: top={top} bottom={bottom}"
        )
        self.assertLessEqual(
            abs(left - right), 6, f"icon not horizontally centered: left={left} right={right}"
        )


@unittest.skipUnless(_HAVE_PIL and _HAVE_CAIROSVG, "Pillow+cairosvg not available")
class BrandIconMatchesSvgTests(unittest.TestCase):
    def test_committed_png_matches_svg_render(self) -> None:
        import io

        with Image.open(ICON) as img:
            size = img.size[0]
            committed = img.convert("RGB")
        with Image.open(
            io.BytesIO(
                cairosvg.svg2png(url=str(SVG), output_width=size, output_height=size)
            )
        ) as r:
            rendered = r.convert("RGB")
        diff = ImageChops.difference(committed, rendered)
        pixels = list(diff.getdata())
        mad = sum(sum(p) for p in pixels) / (len(pixels) * 3)
        # 0 in practice; small tolerance for cairosvg version jitter. A drifted or
        # stale PNG (different drawing) diverges far past this.
        self.assertLess(
            mad, 3.0, f"assets/dictate.png differs from dictate.svg (mad={mad:.2f}); "
            "regenerate with scripts/render_brand_icons.py"
        )


if __name__ == "__main__":
    unittest.main()
