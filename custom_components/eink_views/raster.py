"""Turn an SVG document into a 1-bit PNG. No Home Assistant imports, so it stays testable."""

from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image

FONTS_DIR = Path(__file__).parent / "fonts"
THRESHOLD = 128


def svg_to_png(svg: str, width: int, height: int) -> bytes:
    """Rasterise with bundled fonts only and threshold to pure black and white."""
    raw = resvg_py.svg_to_bytes(
        svg_string=svg,
        width=width,
        height=height,
        background="white",
        font_dirs=[str(FONTS_DIR / "TRMNL"), str(FONTS_DIR / "Inter")],
        skip_system_fonts=True,
    )
    with Image.open(io.BytesIO(bytes(raw))) as image:
        gray = image.convert("L")
    binary = gray.point(lambda value: 255 if value >= THRESHOLD else 0).convert(
        "1", dither=Image.Dither.NONE
    )
    out = io.BytesIO()
    binary.save(out, format="PNG", optimize=True)
    return out.getvalue()
