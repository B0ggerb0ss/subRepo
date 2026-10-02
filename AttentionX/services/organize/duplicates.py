"""Exact and near-duplicate candidates (never deletes anything).

Exact: identical bytes are already one Asset with several ImportInstances.
Near: resized / re-encoded copies.
  1. candidate filter: pHash Hamming <= PHASH_MAX and dHash Hamming <= DHASH_MAX;
  2. verification (all required):
     - aspect ratios within ASPECT_TOL (a substantial crop is "related", not duplicate),
     - structural similarity (SSIM) of 64x64 grayscale thumbnails >= SSIM_MIN
       (CLIP was rejected as verifier: a 50% downscale of a small photo moved
       CLIP cosine to 0.79 while pHash stayed identical; see reports),
     - text agreement when both images carry substantial OCR text (>= 20 chars):
       character similarity of whitespace-free normalized text >= TEXT_MIN; one
       text-heavy image vs one without text is rejected; spurious OCR on photos
       (< 20 chars) is ignored. Two different LinkedIn posts share header/footer
       chrome but not their text, so they are rejected here;
  3. groups are stars around a representative (largest pixel count, then
     earliest import): every member must verify against the representative,
     so A~B and B~C never chains A into C's group.
Thresholds are validation-tuned (reports/evaluation.md), not universal.
"""
from __future__ import annotations

import json
import re
import time

import numpy as np

from services.library.repository import Repository

PHASH_MAX = 12
DHASH_MAX = 14
ASPECT_TOL = 0.03
SSIM_MIN = 0.90  # dev-tuned (reports/tuning_dev.json)
TEXT_MIN = 0.85
TEXT_MIN_CHARS = 20
METHOD = "phash+dhash->aspect+ssim64+ocr_charsim/3"


def _hex_to_u64(h: str) -> np.uint64:
    return np.uint64(int(h, 16))


_POP8 = np.array([bin(b).count("1") for b in range(256)], dtype=np.int64)


def _popcount(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.uint64)
    c = np.zeros(x.shape, dtype=np.int64)
    for s in range(0, 64, 8):
        c += _POP8[((x >> np.uint64(s)) & np.uint64(0xFF)).astype(np.int64)]
    return c


def _tokens(repo: Repository, asset_id: str) -> str:
    """Whitespace-free normalized OCR text: robust to OCR merging/splitting words
    at different scales (a downscaled copy often loses inter-word spaces)."""
    r = repo.query_one("SELECT norm_text FROM ocr_docs WHERE asset_id=?", (asset_id,))
    return re.sub(r"\s+", "", r["norm_text"]) if r else ""


def _facts(repo: Repository, library_id: str) -> list[dict]:
    """Per-asset hash facts from indexed columns (O(rows), no metadata JSON parsing).
    Rows committed before schema v5 fall back to the metadata payload."""
    out = []
    legacy = []
    for r in repo.query("SELECT id, width, height, created_at, phash64, dhash64 FROM assets WHERE library_id=? AND"
                        " deleted_at IS NULL AND metadata_revision > 0", (library_id,)):
        if r["phash64"] and r["dhash64"] and r["width"] and r["height"]:
            out.append({"id": r["id"], "w": r["width"], "h": r["height"], "created": r["created_at"],
                        "phash": r["phash64"], "dhash": r["dhash64"]})
        else:
            legacy.append(r["id"])
    for aid in legacy:
        r = repo.query_one("SELECT a.created_at, m.payload FROM assets a JOIN metadata_revisions m ON m.asset_id=a.id"
                           " AND m.revision=a.metadata_revision WHERE a.id=?", (aid,))
        img = (json.loads(r["payload"]).get("image") or {}) if r else {}
        h = img.get("hashes") or {}
        if "phash64" in h:
            out.append({"id": aid, "w": img["display_width"], "h": img["display_height"], "created": r["created_at"],
                        "phash": h["phash64"], "dhash": h["dhash64"]})
    return out


def _thumb_gray(repo: Repository, library_root, asset_id: str) -> np.ndarray | None:
    import cv2
    from PIL import Image

    r = repo.query_one("SELECT thumb_ref FROM assets WHERE id=?", (asset_id,))
    if r is None or not r["thumb_ref"]:
        return None
    p = library_root / r["thumb_ref"]
    if not p.is_file():
        return None
    g = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
    return cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    import cv2

    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (7, 7), 1.5), cv2.GaussianBlur(b, (7, 7), 1.5)
    va = cv2.GaussianBlur(a * a, (7, 7), 1.5) - mu_a ** 2
    vb = cv2.GaussianBlur(b * b, (7, 7), 1.5) - mu_b ** 2
    cov = cv2.GaussianBlur(a * b, (7, 7), 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))
    return float(m.mean())


def verify_pair(a: dict, b: dict, ga: np.ndarray | None, gb: np.ndarray | None, ta: str, tb: str) -> tuple[bool, dict]:
    ev: dict = {}
    ra, rb = a["w"] / a["h"], b["w"] / b["h"]
    ev["aspect_delta"] = round(abs(ra - rb) / max(ra, rb), 4)
    if ev["aspect_delta"] > ASPECT_TOL:
        return False, ev | {"rejected": "aspect (crop => related, not duplicate)"}
    if ga is None or gb is None:
        return False, ev | {"rejected": "missing thumbnail"}
    ev["ssim64"] = round(ssim(ga, gb), 4)
    if ev["ssim64"] < SSIM_MIN:
        return False, ev | {"rejected": "pixel structure differs"}
    la, lb = len(ta), len(tb)
    if la >= TEXT_MIN_CHARS and lb >= TEXT_MIN_CHARS:
        from rapidfuzz import fuzz

        sim = fuzz.ratio(ta, tb) / 100.0
        ev["ocr_char_similarity"] = round(sim, 4)
        if sim < TEXT_MIN:
            return False, ev | {"rejected": "text differs (shared UI chrome is not duplication)"}
    elif max(la, lb) >= 4 * TEXT_MIN_CHARS and min(la, lb) < 5:
        return False, ev | {"rejected": "one image is text-heavy, the other has no text"}
    return True, ev


def candidate_pairs(facts: list[dict], focus: set[str] | None = None) -> list[tuple[int, int, int, int]]:
    """(i, j, phash_dist, dhash_dist) pairs under the perceptual thresholds."""
    if len(facts) < 2:
        return []
    P = np.array([_hex_to_u64(f["phash"]) for f in facts], dtype=np.uint64)
    D = np.array([_hex_to_u64(f["dhash"]) for f in facts], dtype=np.uint64)
    idx = range(len(facts)) if focus is None else [i for i, f in enumerate(facts) if f["id"] in focus]
    pairs = set()
    for i in idx:
        pd = _popcount(P ^ P[i])
        dd = _popcount(D ^ D[i])
        for j in np.nonzero((pd <= PHASH_MAX) & (dd <= DHASH_MAX))[0]:
            j = int(j)
            if j != i:
                a, b = (i, j) if i < j else (j, i)
                pairs.add((a, b, int(pd[j]), int(dd[j])))
    return sorted(pairs)


def find_duplicate_groups(repo: Repository, library_id: str, focus: set[str] | None = None,
                          library_root=None) -> list[dict]:
    facts = _facts(repo, library_id)
    pairs = candidate_pairs(facts, focus)
    if not pairs:
        return []
    ids = sorted({facts[i]["id"] for p in pairs for i in p[:2]})
    from services.library.config import get_config

    root = library_root or get_config().library_root
    grays = {aid: _thumb_gray(repo, root, aid) for aid in ids}
    toks = {aid: _tokens(repo, aid) for aid in ids}
    verified: dict[tuple[str, str], dict] = {}
    for i, j, pd, dd in pairs:
        a, b = facts[i], facts[j]
        ok, ev = verify_pair(a, b, grays.get(a["id"]), grays.get(b["id"]), toks[a["id"]], toks[b["id"]])
        if ok:
            verified[(a["id"], b["id"])] = verified[(b["id"], a["id"])] = ev | {"phash_hamming": pd,
                                                                                "dhash_hamming": dd}
    # Star groups: representatives in priority order claim verified neighbours.
    by_id = {f["id"]: f for f in facts}
    nodes = sorted({a for a, _ in verified}, key=lambda x: (-by_id[x]["w"] * by_id[x]["h"], by_id[x]["created"], x))
    used: set[str] = set()
    groups = []
    for rep in nodes:
        if rep in used:
            continue
        members = [b for (a, b) in verified if a == rep and b not in used]
        if not members:
            continue
        used.add(rep)
        used.update(members)
        groups.append({"representative": rep, "members": sorted(members),
                       "evidence": {m: verified[(rep, m)] for m in members}})
    return groups
