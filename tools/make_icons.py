"""Regenerate the icon set from the AEG application icon.

    python tools/make_icons.py aeg.png

The source is a square wordmark on a dark diagonal gradient. Everything is
derived from it: the square icons by scaling, the 2:1 logos by cropping the
band the wordmark sits in, and the banner by rebuilding the gradient at banner
size and laying the wordmark over it, because a 240 pixel square has nothing to
crop a 4:1 banner out of.

Needs Pillow, which the integration itself does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

RED = (229, 0, 47)

BRANDS = Path("custom_components/aeg/brand")
ASSETS = Path("assets")


def _pixel(image: Image.Image, x: int, y: int) -> tuple[int, ...]:
    value = image.getpixel((x, y))
    if not isinstance(value, tuple):
        raise SystemExit("the source image is not in colour")
    return value


def wordmark(source: Image.Image) -> Image.Image:
    """Cut the letters out of the source as solid red with an alpha channel.

    Redness is a good enough mask: the gradient behind the letters is grey, so
    anything much redder than its own green and blue is glyph.
    """
    red, green, blue = source.split()
    mask = ImageChops.subtract(red, ImageChops.lighter(green, blue))
    mask = mask.point(lambda value: min(255, value * 3))
    box = mask.getbbox()
    if box is None:
        raise SystemExit("found no wordmark in the source")
    mask = mask.crop(box)
    glyphs = Image.new("RGBA", mask.size, (*RED, 0))
    glyphs.putalpha(mask)
    return glyphs


def square(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def logo(source: Image.Image, width: int, height: int) -> Image.Image:
    """Crop the horizontal band holding the wordmark, at the target aspect."""
    source_width, source_height = source.size
    band = round(source_width * height / width)
    top = (source_height - band) // 2
    cropped = source.crop((0, top, source_width, top + band))
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def banner(
    source: Image.Image, glyphs: Image.Image, width: int, height: int
) -> Image.Image:
    """Rebuild the gradient at banner size and centre the wordmark on it."""
    source_width, source_height = source.size
    corners = Image.new("RGB", (2, 2))
    corners.putpixel((0, 0), _pixel(source, 0, 0))
    corners.putpixel((1, 0), _pixel(source, source_width - 1, 0))
    corners.putpixel((0, 1), _pixel(source, 0, source_height - 1))
    corners.putpixel((1, 1), _pixel(source, source_width - 1, source_height - 1))
    out = corners.resize((width, height), Image.Resampling.BICUBIC).convert("RGBA")

    target = round(width * 0.3)
    scaled = glyphs.resize(
        (target, round(target * glyphs.height / glyphs.width)),
        Image.Resampling.LANCZOS,
    )
    out.alpha_composite(
        scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2)
    )
    return out.convert("RGB")


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    print(f"{path} {image.width} x {image.height}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    source = Image.open(argv[1]).convert("RGB")
    glyphs = wordmark(source)

    save(square(source, 256), BRANDS / "icon.png")
    save(square(source, 512), BRANDS / "icon@2x.png")
    save(logo(source, 256, 128), BRANDS / "logo.png")
    save(logo(source, 512, 256), BRANDS / "logo@2x.png")
    save(banner(source, glyphs, 1280, 320), ASSETS / "header.png")
    save(square(source, 64), ASSETS / "favicon-64.png")
    save(square(source, 32), ASSETS / "favicon-32.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
