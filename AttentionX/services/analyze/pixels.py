"""Still-image decoding and pixel measurements (Pillow + OpenCV).

Pillow owns safe decoding, EXIF orientation and color conversion; OpenCV owns
measurements. Nothing here is a semantic classifier: values are proxies
(sharpness, exposure, flatness...) with names that say what was measured.

Coordinate convention used across the library: *display space* is the image
after applying its EXIF orientation. Normalized coordinates are display-space
pixels divided by display width/height.
"""
from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PIXELS_VERSION = "pixels/1.0"
METRIC_LONG_EDGE = 768


class ImageAdmissionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class DecodedImage:
    rgb: np.ndarray            # display-oriented RGB uint8, representative frame
    format: str
    mime: str
    stored_size: tuple[int, int]
    display_size: tuple[int, int]
    exif_orientation: int
    color_mode: str
    icc_profile: bool
    animated: bool
    frame_count: int
    camera_exif: bool


def probe_image(path: Path, max_bytes: int, max_pixels: int) -> dict:
    """Header-only admission check. Raises ImageAdmissionError; never decodes pixels."""
    size = path.stat().st_size
    if size == 0:
        raise ImageAdmissionError("empty_file", "file is empty")
    if size > max_bytes:
        raise ImageAdmissionError("too_large", f"file exceeds {max_bytes // (1024 * 1024)} MB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as im:
                fmt = im.format
                w, h = im.size
                n_frames = getattr(im, "n_frames", 1)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageAdmissionError("decompression_bomb", "image pixel count exceeds decoder safety limit")
    except Exception:
        raise ImageAdmissionError("unreadable", "not a readable image file")
    if fmt not in SUPPORTED_FORMATS:
        raise ImageAdmissionError(
            "unsupported_format",
            f"format {fmt or 'unknown'} is not supported (JPEG, PNG, WebP only)",
        )
    if w <= 0 or h <= 0:
        raise ImageAdmissionError("invalid_dimensions", "image has no pixels")
    if w * h > max_pixels:
        raise ImageAdmissionError(
            "too_many_pixels", f"{w}x{h} exceeds the {max_pixels / 1e6:.0f} MP limit"
        )
    return {"format": fmt, "mime": SUPPORTED_FORMATS[fmt], "width": w, "height": h, "frames": n_frames}


def decode_image(path: Path, max_pixels: int) -> DecodedImage:
    """Fully decode (frame 0 for animations) with orientation applied."""
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as im:
            fmt = im.format
            stored = im.size
            frames = getattr(im, "n_frames", 1)
            animated = bool(getattr(im, "is_animated", False)) and frames > 1
            exif = im.getexif()
            orientation = int(exif.get(0x0112, 1) or 1)
            if orientation not in range(1, 9):
                orientation = 1
            camera = bool(exif.get(0x010F) or exif.get(0x0110))
            icc = bool(im.info.get("icc_profile"))
            mode = im.mode
            im.seek(0)
            im.load()
            oriented = ImageOps.exif_transpose(im) if orientation != 1 else im.copy()
    except Image.DecompressionBombError:
        raise ImageAdmissionError("decompression_bomb", "image pixel count exceeds decoder safety limit")
    except ImageAdmissionError:
        raise
    except Exception:
        raise ImageAdmissionError("corrupt", "image data could not be decoded")
    if oriented.mode in ("RGBA", "LA", "P", "PA"):
        rgba = oriented.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        oriented = Image.alpha_composite(bg, rgba)
    rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
    return DecodedImage(
        rgb=rgb,
        format=fmt,
        mime=SUPPORTED_FORMATS.get(fmt, "application/octet-stream"),
        stored_size=stored,
        display_size=(rgb.shape[1], rgb.shape[0]),
        exif_orientation=orientation,
        color_mode=mode,
        icc_profile=icc,
        animated=animated,
        frame_count=frames,
        camera_exif=camera,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resize_long_edge(rgb: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    scale = long_edge / max(h, w)
    if scale >= 1:
        return rgb
    return cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))),
                      interpolation=cv2.INTER_AREA)


def dhash64(rgb: np.ndarray) -> str:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def phash64(rgb: np.ndarray) -> str:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small)[:8, :8].flatten()
    med = np.median(dct[1:])
    bits = dct > med
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming64(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def measure(rgb: np.ndarray) -> tuple[dict[str, float], list[dict]]:
    """Pixel metrics at a fixed long edge (METRIC_LONG_EDGE)."""
    small = resize_long_edge(rgb, METRIC_LONG_EDGE)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    luma = gray.astype(np.float32) / 255.0
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float((edges > 0).mean())

    # Axis-aligned structure: share of gradient energy on near-horizontal/vertical
    # directions. UI captures and documents score high; natural photos lower.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    strong = mag > 40
    if strong.any():
        ang = np.degrees(np.arctan2(np.abs(gy[strong]), np.abs(gx[strong])))
        axis_aligned = float(((ang < 5) | (ang > 85)).mean())
    else:
        axis_aligned = 0.0

    # Flatness: fraction of 8x8 blocks with (almost) no variation.
    h8, w8 = (gray.shape[0] // 8) * 8, (gray.shape[1] // 8) * 8
    if h8 and w8:
        blocks = gray[:h8, :w8].reshape(h8 // 8, 8, w8 // 8, 8).std(axis=(1, 3))
        flat_fraction = float((blocks < 1.5).mean())
    else:
        flat_fraction = 0.0

    r, g, b = [small[..., i].astype(np.float32) for i in range(3)]
    rg, yb = r - g, 0.5 * (r + g) - b
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    unique_colors = float(len(np.unique((small[::2, ::2] // 8).reshape(-1, 3), axis=0)))

    # Letterbox bars: persistent near-black rows at top and bottom.
    row_mean = luma.mean(axis=1)
    top = int(np.argmax(row_mean > 0.06)) if (row_mean > 0.06).any() else len(row_mean)
    bottom = int(np.argmax(row_mean[::-1] > 0.06)) if (row_mean > 0.06).any() else len(row_mean)

    metrics = {
        "sharpness_laplacian_var": round(lap_var, 3),
        "luma_p05": round(float(np.quantile(luma, 0.05)), 4),
        "luma_p50": round(float(np.quantile(luma, 0.50)), 4),
        "luma_p95": round(float(np.quantile(luma, 0.95)), 4),
        "clip_black_fraction": round(float((luma <= 0.02).mean()), 4),
        "clip_white_fraction": round(float((luma >= 0.98).mean()), 4),
        "edge_density": round(edge_density, 4),
        "axis_aligned_gradient_fraction": round(axis_aligned, 4),
        "flat_block_fraction": round(flat_fraction, 4),
        "colorfulness": round(colorfulness, 3),
        "unique_color_bins": unique_colors,
        "letterbox_top_fraction": round(top / len(row_mean), 4),
        "letterbox_bottom_fraction": round(bottom / len(row_mean), 4),
        "aspect_ratio": round(rgb.shape[1] / rgb.shape[0], 4),
        "metric_long_edge": float(max(small.shape[:2])),
    }
    return metrics, _palette(small)


def _palette(small: np.ndarray, k: int = 5) -> list[dict]:
    # Deterministic median-cut quantization (fixed algorithm, no random init).
    pil = Image.fromarray(small).quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = pil.getpalette()[: k * 3]
    counts = np.bincount(np.asarray(pil).flatten(), minlength=k)[:k]
    total = counts.sum() or 1
    out = []
    for i in np.argsort(-counts):
        if counts[i] == 0:
            continue
        rr, gg, bb = pal[i * 3: i * 3 + 3]
        out.append({"hex": f"#{rr:02x}{gg:02x}{bb:02x}", "fraction": round(float(counts[i] / total), 4)})
    return out


def make_thumbnail(rgb: np.ndarray, long_edge: int) -> bytes:
    small = resize_long_edge(rgb, long_edge)
    import io

    buf = io.BytesIO()
    Image.fromarray(small).save(buf, format="WEBP", quality=82, method=4)
    return buf.getvalue()
