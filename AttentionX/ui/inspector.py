"""Inspector rendering: overlays drawn from stored evidence only.

- OCR matches: the matched regions' polygons (normalized display coords).
- Object filters: only the detection box that matched.
- Visual-semantic matches: no box and no percentage; the whole image is the
  evidence. A selected query crop is drawn as a dashed-style rectangle.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

PREVIEW_LONG_EDGE = 1400
COLORS = {
    "OCR_PHRASE": (255, 196, 0),
    "OCR_LEXICAL": (0, 170, 255),
    "OCR_SEMANTIC": (160, 90, 255),
    "OBJECT_DETECTION": (0, 200, 90),
    "CROP": (255, 64, 64),
    "ALL_OCR": (120, 120, 120),
}


def preview_path(library, asset) -> Path | None:
    """Display-oriented preview derivative (never modifies the original)."""
    rel = f"derived/previews/{asset.content_hash[:2]}/{asset.content_hash}_{PREVIEW_LONG_EDGE}.webp"
    out = library.cfg.library_root / rel
    if out.exists():
        return out
    src = library.path_of(asset.original_ref)
    if src is None:
        return None
    try:
        with Image.open(src) as im:
            im.seek(0)
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((PREVIEW_LONG_EDGE, PREVIEW_LONG_EDGE))
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            im.save(tmp, format="WEBP", quality=85)
            tmp.replace(out)
    except Exception:
        return None
    return out


def draw_overlays(base: Image.Image, polygons: list[tuple[str, list]], boxes: list[tuple[str, tuple, str]],
                  crop: tuple | None = None) -> Image.Image:
    img = base.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    W, H = img.size
    lw = max(2, round(max(W, H) / 400))
    for kind, poly in polygons:
        color = COLORS.get(kind, (255, 196, 0))
        pts = [(x * W, y * H) for x, y in poly]
        d.polygon(pts, fill=color + (60,), outline=color + (255,), width=lw)
    for kind, box, label in boxes:
        color = COLORS.get(kind, (0, 200, 90))
        x0, y0, x1, y1 = box
        d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=color + (255,), width=lw)
        if label:
            d.rectangle([x0 * W, max(0, y0 * H - 18), x0 * W + 8 * len(label) + 8, y0 * H], fill=color + (220,))
            d.text((x0 * W + 4, max(0, y0 * H - 16)), label, fill=(0, 0, 0, 255))
    if crop is not None:
        x0, y0, x1, y1 = crop
        d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=COLORS["CROP"] + (255,), width=lw + 1)
    return Image.alpha_composite(img, overlay).convert("RGB")


def render_inspector_image(library, asset_id: str, hit=None, show_all_ocr: bool = False,
                           crop: tuple | None = None) -> np.ndarray | None:
    asset = library.get_asset(asset_id)
    if asset is None:
        return None
    p = preview_path(library, asset)
    if p is None:
        return None
    base = Image.open(p)
    polygons: list[tuple[str, list]] = []
    boxes: list[tuple[str, tuple, str]] = []
    if show_all_ocr:
        detail = library.asset_detail(asset_id)
        ocr = (detail.get("metadata") or {}).get("ocr") or {}
        polygons += [("ALL_OCR", r["polygon"]) for r in ocr.get("regions", [])]
    if hit is not None:
        for ev in hit.reasons:
            if ev.reason in {"OCR_PHRASE", "OCR_LEXICAL", "OCR_SEMANTIC"}:
                polygons += [(ev.reason, poly) for poly in ev.polygons]
            elif ev.reason == "OBJECT_DETECTION" and ev.box is not None:
                boxes.append(("OBJECT_DETECTION", ev.box, ev.detail.replace("detected ", "")))
    return np.asarray(draw_overlays(base, polygons, boxes, crop))


def evidence_markdown(hit) -> str:
    if hit is None:
        return ""
    lines = []
    for ev in hit.reasons:
        line = f"- **{ev.reason}** — {ev.detail}"
        if ev.score is not None and ev.score_kind:
            line += f"  \n  `{ev.score_kind}={ev.score}`"
        if ev.excerpt:
            ex = ev.excerpt if len(ev.excerpt) < 300 else ev.excerpt[:300] + "…"
            line += f"  \n  > {ex}"
        lines.append(line)
    ranks = ", ".join(f"{k}#{v}" for k, v in sorted(hit.channel_ranks.items()))
    if ranks:
        lines.append(f"\nChannel ranks: {ranks}. Fused rank score {hit.score:.4f} is an ordering score, "
                     "not a probability of relevance.")
    if hit.duplicate_count:
        lines.append(f"\n{hit.duplicate_count} near-duplicate(s) collapsed under this result.")
    return "\n".join(lines) or "_No stored evidence (filter-only browse)._"
