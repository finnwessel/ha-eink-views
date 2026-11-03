"""Turn an SVG document into 1-bit PNGs. No Home Assistant imports, so it stays testable."""

from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image, ImageChops

FONTS_DIR = Path(__file__).parent / "fonts"
THRESHOLD = 128

# Which pixels a layer inks:
#   all    everything dark, red included (black-and-white displays)
#   black  dark but not red (black plane of a black/white/red display)
#   red    clearly red only (red plane of a black/white/red display)
LAYERS = ("all", "black", "red")
FORMATS = ("png", "bmp")


def _mask(channel: Image.Image, below: bool) -> Image.Image:
    """255 where the channel is below the threshold (below=True) or at/above it."""
    if below:
        return channel.point(lambda value: 255 if value < THRESHOLD else 0)
    return channel.point(lambda value: 255 if value >= THRESHOLD else 0)


def _encode(ink: Image.Image) -> bytes:
    """Inked pixels black, the rest white, as a 1-bit PNG."""
    binary = ImageChops.invert(ink).convert("1", dither=Image.Dither.NONE)
    out = io.BytesIO()
    binary.save(out, format="PNG", optimize=True)
    return out.getvalue()


def svg_to_layers(svg: str, width: int, height: int) -> dict[str, bytes]:
    """Rasterise once with bundled fonts only and split into the LAYERS."""
    raw = resvg_py.svg_to_bytes(
        svg_string=svg,
        width=width,
        height=height,
        background="white",
        font_dirs=[str(FONTS_DIR / "TRMNL"), str(FONTS_DIR / "Inter")],
        skip_system_fonts=True,
    )
    with Image.open(io.BytesIO(bytes(raw))) as image:
        rgb = image.convert("RGB")
    red_channel, green, blue = rgb.split()
    dark = _mask(rgb.convert("L"), below=True)
    red = ImageChops.multiply(
        _mask(red_channel, below=False),
        ImageChops.multiply(_mask(green, below=True), _mask(blue, below=True)),
    )
    return {
        "all": _encode(ImageChops.lighter(dark, red)),
        "black": _encode(ImageChops.subtract(dark, red)),
        "red": _encode(red),
    }


def png_to_bmp(png: bytes) -> bytes:
    """Same 1-bit image as an uncompressed BMP.

    Devices without PSRAM may lack the memory for a PNG decoder next to the image
    buffer (zlib needs about 40 KB); a BMP is decoded row by row without one.
    """
    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert("1").save(out, format="BMP")
    return out.getvalue()


def svg_to_png(svg: str, width: int, height: int) -> bytes:
    """Single black-and-white image; red counts as black."""
    return svg_to_layers(svg, width, height)["all"]
