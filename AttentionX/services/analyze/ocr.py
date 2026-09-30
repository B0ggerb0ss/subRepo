"""OCR adapter: engine selection, bounded overlapping tiling, reading order.

Engines (explicit, recorded in provenance; never silently swapped):
- ``rapidocr``: rapidocr_onnxruntime 1.4.4 with the PP-OCRv4 det/rec + mobile
  cls ONNX models shipped in its wheel (hashes pinned in docs/model-manifest.json).
- ``tesseract``: the installed ``tesseract`` CLI with its language data; used
  only when enabled as a fallback and RapidOCR is unavailable.

Screenshots need spatial fidelity: the image is never shrunk to a single small
canvas. It is covered by overlapping tiles at >= native scale (bounded by
``Limits.ocr_max_tiles`` / ``ocr_max_seconds``); tile hits are mapped back to
display coordinates and overlap duplicates are merged without collapsing
legitimately repeated lines at different positions. Incomplete coverage is
recorded, never hidden.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

OCR_VERSION = "ocr/1.1"
NORMALIZATION_VERSION = "norm/1.0"

_TYPO = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
})
_WS = re.compile(r"\s+")


def normalize_for_search(text: str) -> str:
    """Search view of text (raw text is always kept separately).

    NFKC, typographic quotes/dashes to ASCII, casefold, collapse whitespace.
    Punctuation is preserved so ``C++``, ``C#``, URLs and ``$120k`` stay
    distinguishable.
    """
    s = unicodedata.normalize("NFKC", text).translate(_TYPO).casefold()
    return _WS.sub(" ", s).strip()


class OCRUnavailable(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RawLine:
    polygon_px: list[tuple[float, float]]     # display-space pixels
    text: str
    score: float | None
    tile_id: str


@dataclass
class Tile:
    tile_id: str
    x0: int
    y0: int
    x1: int
    y1: int
    scale: float
    status: str = "skipped"


@dataclass
class OCRRun:
    engine: str
    engine_version: str
    model_ids: list[str]
    script_scope: str
    lines: list[RawLine]
    tiles: list[Tile]
    complete: bool
    incomplete_reason: str | None
    elapsed_s: float
    engine_digest: str
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

class RapidOCREngine:
    name = "rapidocr"
    script_scope = "PP-OCRv4 ch recognizer: Simplified Chinese + Latin (English); no Arabic/Devanagari"

    def __init__(self, model_dir: Path | None = None, expected: dict[str, str] | None = None) -> None:
        try:
            import rapidocr_onnxruntime
            from rapidocr_onnxruntime import RapidOCR
        except Exception as e:
            raise OCRUnavailable("ocr_engine_missing", "rapidocr_onnxruntime is not installed") from e
        pkg_dir = Path(rapidocr_onnxruntime.__file__).parent
        model_dir = Path(os.getenv("ATTENTIONX_RAPIDOCR_MODEL_DIR", model_dir or pkg_dir / "models"))
        files = {
            "det": "ch_PP-OCRv4_det_infer.onnx",
            "rec": "ch_PP-OCRv4_rec_infer.onnx",
            "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        }
        paths = {k: model_dir / v for k, v in files.items()}
        missing = [v for k, v in files.items() if not paths[k].is_file()]
        if missing:
            raise OCRUnavailable("ocr_model_missing", f"OCR weights missing: {', '.join(missing)}")
        digests = {}
        for k, p in paths.items():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            if expected and expected.get(p.name) and expected[p.name] != digest:
                raise OCRUnavailable("ocr_model_mismatch", f"OCR weights {p.name} do not match the pinned hash")
            digests[p.name] = digest
        self.model_ids = sorted(files.values())
        self.digest = hashlib.sha256("".join(digests[n] for n in self.model_ids).encode()).hexdigest()
        try:
            from importlib.metadata import version

            self.version = version("rapidocr_onnxruntime")
        except Exception:
            self.version = "unknown"
        self._engine = RapidOCR(
            det_model_path=str(paths["det"]),
            rec_model_path=str(paths["rec"]),
            cls_model_path=str(paths["cls"]),
        )
        self.text_score_threshold = 0.5  # engine default (config.yaml Global.text_score)

    def recognize(self, rgb: np.ndarray) -> list[tuple[list[tuple[float, float]], str, float | None]]:
        result, _ = self._engine(np.ascontiguousarray(rgb))
        out = []
        for box, text, score in result or []:
            out.append(([(float(x), float(y)) for x, y in box], str(text), float(score)))
        return out


class TesseractEngine:
    name = "tesseract"

    def __init__(self, languages: tuple[str, ...] = ("en",)) -> None:
        exe = shutil.which("tesseract")
        if exe is None:
            raise OCRUnavailable("ocr_engine_missing", "tesseract binary not installed")
        lang_map = {"en": "eng"}
        self.lang = "+".join(lang_map.get(l, l) for l in languages)
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30)
        have = set(out.stdout.split())
        missing = [l for l in self.lang.split("+") if l not in have]
        if missing:
            raise OCRUnavailable("ocr_model_missing", f"tesseract language data missing: {missing}")
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
        self.version = (v.stdout or v.stderr).split("\n")[0].strip()
        self.exe = exe
        self.model_ids = [f"tesseract-{self.lang}"]
        self.digest = hashlib.sha256(f"{self.version}|{self.lang}".encode()).hexdigest()
        self.script_scope = f"tesseract languages: {self.lang}"

    def recognize(self, rgb: np.ndarray) -> list[tuple[list[tuple[float, float]], str, float | None]]:
        import tempfile

        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="ax-tess-") as tmp:
            src = Path(tmp) / "tile.png"
            Image.fromarray(rgb).save(src)
            res = subprocess.run(
                [self.exe, str(src), "stdout", "-l", self.lang, "--psm", "3", "tsv"],
                capture_output=True, text=True, timeout=120,
            )
        if res.returncode != 0:
            raise RuntimeError("tesseract failed")
        lines: dict[tuple, dict] = {}
        for row in res.stdout.splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) < 12 or parts[0] != "5" or not parts[11].strip():
                continue
            key = (parts[2], parts[3], parts[4])  # block, paragraph, line
            x, y, w, h = map(int, parts[6:10])
            conf = float(parts[10])
            e = lines.setdefault(key, {"words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h, "confs": []})
            e["words"].append(parts[11])
            e["x0"], e["y0"] = min(e["x0"], x), min(e["y0"], y)
            e["x1"], e["y1"] = max(e["x1"], x + w), max(e["y1"], y + h)
            if conf >= 0:
                e["confs"].append(conf / 100.0)
        out = []
        for e in lines.values():
            poly = [(e["x0"], e["y0"]), (e["x1"], e["y0"]), (e["x1"], e["y1"]), (e["x0"], e["y1"])]
            score = float(np.mean(e["confs"])) if e["confs"] else None
            out.append((poly, " ".join(e["words"]), score))
        return out


def build_engine(languages: tuple[str, ...], allow_tesseract: bool, expected_hashes: dict[str, str] | None):
    """Return (engine, fallback_note). Raises OCRUnavailable when nothing works."""
    unsupported = [l for l in languages if l not in {"en", "ch"}]
    errors = []
    if not unsupported:
        try:
            return RapidOCREngine(expected=expected_hashes), None
        except OCRUnavailable as e:
            errors.append(e)
    if allow_tesseract:
        try:
            eng = TesseractEngine(languages)
            reason = errors[0].code if errors else "language_not_in_rapidocr_profile"
            return eng, f"fallback:tesseract ({reason})"
        except OCRUnavailable as e:
            errors.append(e)
    if unsupported and not errors:
        raise OCRUnavailable("ocr_language_unsupported", f"no provisioned recognizer for {unsupported}")
    raise errors[0]


# ---------------------------------------------------------------------------
# Tiling + merge + reading order
# ---------------------------------------------------------------------------

def plan_tiles(width: int, height: int, tile: int, overlap: int) -> tuple[float, list[Tile]]:
    """Plan overlapping tiles in display space.

    Scale is 1.5-2x for small and typical screenshot widths (tiny text and word
    spacing survive recognition), 1 for wide images, and only drops below 1 for
    very wide images (> 2 tiles across), keeping each tile under RapidOCR's
    internal 2000 px cap.
    """
    scale = 1.0
    if width < 640:
        scale = min(2.0, 1000.0 / width)
    elif width <= 1400:
        # PP-OCRv4's recognizer drops inter-word spaces on ~15 px UI text; 1.5x
        # restores them (measured in reports/evaluation.md) at ~1.5x OCR cost.
        scale = 1.5
    elif width > 2 * tile:
        scale = (2 * tile) / width
    sw, sh = width * scale, height * scale

    def spans(length: float) -> list[tuple[float, float]]:
        if length <= tile * 1.25:
            return [(0.0, length)]
        step = tile - overlap
        out, start = [], 0.0
        while True:
            end = min(start + tile, length)
            out.append((start, end))
            if end >= length:
                break
            start += step
        return out

    tiles = []
    for ri, (y0, y1) in enumerate(spans(sh)):
        for ci, (x0, x1) in enumerate(spans(sw)):
            tiles.append(Tile(
                tile_id=f"t{ri:03d}_{ci:02d}",
                x0=int(round(x0 / scale)), y0=int(round(y0 / scale)),
                x1=int(round(x1 / scale)), y1=int(round(y1 / scale)),
                scale=scale,
            ))
    return scale, tiles


def run_ocr(rgb: np.ndarray, engine, tile_edge: int, overlap: int, max_tiles: int,
            max_seconds: float, cancel_check=None) -> OCRRun:
    import cv2

    h, w = rgb.shape[:2]
    scale, tiles = plan_tiles(w, h, tile_edge, overlap)
    started = time.monotonic()
    lines: list[RawLine] = []
    reason = None
    for i, t in enumerate(tiles):
        if cancel_check is not None:
            cancel_check()
        if i >= max_tiles:
            reason = f"tile cap reached ({max_tiles} of {len(tiles)} tiles)"
            break
        if time.monotonic() - started > max_seconds:
            reason = f"time budget exhausted after {i} of {len(tiles)} tiles"
            break
        crop = rgb[t.y0:t.y1, t.x0:t.x1]
        if scale != 1.0:
            crop = cv2.resize(crop, (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))),
                              interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        try:
            hits = engine.recognize(crop)
        except Exception:
            t.status = "error"
            reason = reason or "a tile failed to recognize"
            continue
        t.status = "complete"
        for poly, text, score in hits:
            if not text.strip():
                continue
            mapped = [(t.x0 + x / scale, t.y0 + y / scale) for x, y in poly]
            lines.append(RawLine(mapped, text, score, t.tile_id))
    lines = merge_overlap_duplicates(lines, tiles)
    done = sum(1 for t in tiles if t.status == "complete")
    return OCRRun(
        engine=engine.name,
        engine_version=engine.version,
        model_ids=engine.model_ids,
        script_scope=engine.script_scope,
        lines=lines,
        tiles=tiles,
        complete=reason is None and done == len(tiles),
        incomplete_reason=reason,
        elapsed_s=time.monotonic() - started,
        engine_digest=engine.digest,
        extra={"scale": scale},
    )


def _bbox(poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _inter(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _area(a) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def merge_overlap_duplicates(lines: list[RawLine], tiles: list[Tile]) -> list[RawLine]:
    """Drop copies of the same physical line seen by two overlapping tiles.

    A pair is a duplicate only when both come from *different* tiles, their
    boxes substantially coincide (the smaller box is >= 60% covered), and one
    normalized text contains the other. Identical text at different positions
    (a repeated legitimate line) never overlaps geometrically and is kept.
    The longer (less truncated) text wins.
    """
    boxes = [_bbox(l.polygon_px) for l in lines]
    drop: set[int] = set()
    order = sorted(range(len(lines)), key=lambda i: -len(lines[i].text))
    for pos, i in enumerate(order):
        if i in drop:
            continue
        ni = normalize_for_search(lines[i].text)
        for j in order[pos + 1:]:
            if j in drop or lines[j].tile_id == lines[i].tile_id:
                continue
            small = min(_area(boxes[i]), _area(boxes[j])) or 1.0
            if _inter(boxes[i], boxes[j]) / small < 0.6:
                continue
            nj = normalize_for_search(lines[j].text)
            if nj in ni or ni in nj:
                drop.add(j)
    return [l for k, l in enumerate(lines) if k not in drop]


def reading_order(lines: list[RawLine]) -> list[tuple[RawLine, int, int]]:
    """Return (line, reading_order, line_group) for top-to-bottom, left-to-right text.

    Lines whose vertical extents overlap by >= 50% of the shorter height share
    a row (line_group) and are ordered by x within it.
    """
    items = sorted(((l, _bbox(l.polygon_px)) for l in lines), key=lambda t: (t[1][1], t[1][0]))
    rows: list[list[tuple[RawLine, tuple]]] = []
    for line, box in items:
        placed = False
        if rows:
            last = rows[-1]
            ry0 = min(b[1] for _, b in last)
            ry1 = max(b[3] for _, b in last)
            ov = min(ry1, box[3]) - max(ry0, box[1])
            if ov >= 0.5 * min(box[3] - box[1], ry1 - ry0):
                last.append((line, box))
                placed = True
        if not placed:
            rows.append([(line, box)])
    out = []
    order = 0
    for gi, row in enumerate(rows):
        for line, _ in sorted(row, key=lambda t: t[1][0]):
            out.append((line, order, gi))
            order += 1
    return out
