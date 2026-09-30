"""Deterministic synthetic image fixtures (plumbing tests, not quality evidence)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_MONO if mono else FONT, size)


def make_text_image(path: str | Path, lines: list[str], size: tuple[int, int] = (900, 260),
                    font_size: int = 40, origin: tuple[int, int] = (40, 40), line_gap: int = 20,
                    bg: str = "white", fg: str = "black", fmt: str | None = None) -> dict:
    """Render lines; return {"path", "boxes": [(text, (x0,y0,x1,y1) normalized)]}."""
    im = Image.new("RGB", size, bg)
    dr = ImageDraw.Draw(im)
    f = font(font_size)
    x, y = origin
    boxes = []
    for text in lines:
        b = dr.textbbox((x, y), text, font=f)
        dr.text((x, y), text, fill=fg, font=f)
        boxes.append((text, (b[0] / size[0], b[1] / size[1], b[2] / size[0], b[3] / size[1])))
        y = b[3] + line_gap
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format=fmt)
    return {"path": path, "boxes": boxes}


def make_tall_screenshot(path: str | Path, n_lines: int = 60, width: int = 1080, font_size: int = 30,
                         marker_every: int = 20) -> dict:
    """A long capture (> 2 OCR tiles tall) with a unique marker phrase near the bottom."""
    line_h = int(font_size * 2.2)
    height = 120 + n_lines * line_h
    im = Image.new("RGB", (width, height), "white")
    dr = ImageDraw.Draw(im)
    f = font(font_size)
    texts = []
    for i in range(n_lines):
        t = f"line {i:03d} ordinary feed text"
        if i == n_lines - 3:
            t = "bottom marker train serving skew"
        elif i % marker_every == 0:
            t = "repeated header text"
        dr.text((40, 60 + i * line_h), t, fill="black", font=f)
        texts.append(t)
    path = Path(path)
    im.save(path)
    return {"path": path, "texts": texts, "size": (width, height)}


def make_corrupt_png(path: str | Path) -> Path:
    """Valid PNG signature and IHDR, truncated image data."""
    good = Path(path).with_suffix(".tmp.png")
    Image.new("RGB", (400, 300), "red").save(good)
    data = good.read_bytes()
    good.unlink()
    path = Path(path)
    path.write_bytes(data[:60])
    return path


def make_not_an_image(path: str | Path) -> Path:
    path = Path(path)
    path.write_bytes(b"this is not an image at all\n" * 10)
    return path
