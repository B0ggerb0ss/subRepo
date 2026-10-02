"""Lexical OCR/annotation retrieval over SQLite FTS5.

Literal phrases (``text:"..."``):
  1. candidates: trigram FTS phrase match for >= 3 characters, otherwise a
     bounded parameterized ``instr`` scan (short strings like ``c#``, ``go``);
  2. verification in Python on the normalized document text, with word
     boundaries enforced only where the phrase edge is alphanumeric (so
     ``c++`` matches "C++ dev" but ``java`` does not match "javascript");
  3. match character spans are mapped back to OCR regions for highlighting.
  A semantic neighbour is never reported as a literal phrase match.

Free words: unicode61 FTS (tokenchars '+#') ranked by bm25.
All user input is bound as parameters; FTS strings are built only from
double-quoted, quote-escaped terms.
"""
from __future__ import annotations

import json
import re

from services.analyze.ocr import normalize_for_search
from services.library.repository import Repository


def fts_phrase(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _boundary_ok(doc: str, start: int, end: int, phrase: str) -> bool:
    if phrase[0].isalnum() and start > 0 and doc[start - 1].isalnum():
        return False
    if phrase[-1].isalnum() and end < len(doc) and doc[end].isalnum():
        return False
    return True


def find_occurrences(doc_flat: str, phrase_norm: str) -> list[tuple[int, int]]:
    out = []
    i = doc_flat.find(phrase_norm)
    while i >= 0:
        j = i + len(phrase_norm)
        if _boundary_ok(doc_flat, i, j, phrase_norm):
            out.append((i, j))
        i = doc_flat.find(phrase_norm, i + 1)
    return out


def _regions_for_spans(repo: Repository, asset_id: str, spans: list[tuple[int, int]]) -> list[dict]:
    rows = repo.query(
        "SELECT region_id, raw_text, char_start, char_end, polygon, frame_id, t_s FROM ocr_regions WHERE asset_id=?"
        " ORDER BY order_idx", (asset_id,))
    matches = []
    for s, e in spans:
        regs = [r for r in rows if r["char_start"] < e and r["char_end"] > s]
        matches.append({
            "span": (s, e),
            "region_ids": [r["region_id"] for r in regs],
            "polygons": [json.loads(r["polygon"]) for r in regs],
            "excerpt": " / ".join(r["raw_text"] for r in regs),
            # Video: a span never crosses keyframes (a separator line sits between frames).
            "frame_id": regs[0]["frame_id"] if regs else None,
            "t_s": regs[0]["t_s"] if regs else None,
        })
    return matches


def phrase_search(repo: Repository, phrase: str, eligible: set[str] | None = None,
                  limit_candidates: int = 5000) -> dict[str, list[dict]]:
    """Return {asset_id: [match...]} for assets whose OCR contains the phrase."""
    norm = normalize_for_search(phrase)
    if not norm:
        return {}
    if len(norm) >= 3:
        rows = repo.query(
            "SELECT d.asset_id, d.norm_text FROM ocr_doc_tri t JOIN ocr_docs d ON d.asset_id = t.asset_id"
            " WHERE ocr_doc_tri MATCH ? LIMIT ?", (fts_phrase(norm), limit_candidates))
    else:
        rows = repo.query(
            "SELECT asset_id, norm_text FROM ocr_docs WHERE instr(replace(norm_text, char(10), ' '), ?) > 0"
            " LIMIT ?", (norm, limit_candidates))
    out: dict[str, list[dict]] = {}
    for r in rows:
        if eligible is not None and r["asset_id"] not in eligible:
            continue
        flat = r["norm_text"].replace("\n", " ")
        spans = find_occurrences(flat, norm)
        if spans:
            out[r["asset_id"]] = [{"span": sp, "spaceless": False} for sp in spans]
    if " " in norm:
        for aid, matches in _spaceless_phrase(repo, norm, eligible, set(out), limit_candidates).items():
            out[aid] = matches
    return out


def _spaceless_phrase(repo: Repository, norm: str, eligible: set[str] | None, skip: set[str],
                      limit: int) -> dict[str, list[dict]]:
    """Fallback for multi-word phrases when OCR merged words ("lessonlearned").

    Compares whitespace-free views only; raw OCR text is untouched and the
    evidence says the match ignored word spacing. Word boundaries cannot be
    checked inside merged words, so single-word phrases never use this path.
    """
    words = [w for w in norm.split(" ") if w]
    if not words or any(len(w) < 3 for w in words):
        candidates_sql = "SELECT asset_id, norm_text FROM ocr_docs WHERE instr(replace(replace(norm_text, char(10), ''), ' ', ''), ?) > 0 LIMIT ?"
        rows = repo.query(candidates_sql, ("".join(words), limit))
    else:
        q = " AND ".join(fts_phrase(w) for w in words)
        rows = repo.query("SELECT d.asset_id, d.norm_text FROM ocr_doc_tri t JOIN ocr_docs d ON d.asset_id = t.asset_id"
                          " WHERE ocr_doc_tri MATCH ? LIMIT ?", (q, limit))
    target = "".join(words)
    out: dict[str, list[dict]] = {}
    for r in rows:
        aid = r["asset_id"]
        if aid in skip or (eligible is not None and aid not in eligible):
            continue
        flat = r["norm_text"].replace("\n", " ")
        # Map spaceless offsets back to flat-text offsets.
        idx = [i for i, ch in enumerate(flat) if ch != " "]
        compact = "".join(flat[i] for i in idx)
        spans = []
        k = compact.find(target)
        while k >= 0:
            spans.append((idx[k], idx[k + len(target) - 1] + 1))
            k = compact.find(target, k + 1)
        if spans:
            out[aid] = [{"span": sp, "spaceless": True} for sp in spans]
    return out


def phrase_evidence(repo: Repository, asset_id: str, matches: list[dict]) -> list[dict]:
    """Map phrase match spans to OCR regions (only for results actually shown)."""
    regions = _regions_for_spans(repo, asset_id, [m["span"] for m in matches])
    for reg, m in zip(regions, matches):
        reg["spaceless"] = m["spaceless"]
    return regions


_WORD = re.compile(r"[\w+#][\w+#.\-/$%]*", re.UNICODE)
# Free-text intent only; literal text:"..." phrases keep every word.
STOPWORDS = frozenset("""a an and are as at be but by for from has have i in into is it its of on or our
that the their them they this to was we were what when where which who why will with you your about
after all also any can do does how if just more most not no so some than then there these those up""".split())


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    norm = normalize_for_search(text)
    toks = [t.strip(".-/") for t in _WORD.findall(norm) if t.strip(".-/")]
    return [t for t in toks if not (drop_stopwords and t in STOPWORDS)]


def word_search(repo: Repository, free_text: str, eligible: set[str] | None = None,
                limit: int = 500) -> list[tuple[str, float, list[dict]]]:
    """bm25-ranked OCR word search. Returns [(asset_id, bm25, evidence_regions)]."""
    toks = tokens(free_text)
    if not toks:
        return []
    q = " OR ".join(fts_phrase(t) for t in toks)
    rows = repo.query(
        "SELECT asset_id, bm25(ocr_doc_words) AS s FROM ocr_doc_words WHERE ocr_doc_words MATCH ?"
        " ORDER BY s LIMIT ?", (q, limit))
    out = []
    for r in rows:
        if eligible is not None and r["asset_id"] not in eligible:
            continue
        # bm25() is "lower is better"; expose the positive magnitude.
        out.append((r["asset_id"], -float(r["s"]), False))
    found = {a for a, _, _ in out}
    # Fallback: OCR sometimes merges words ("lessonlearned"); find query words of
    # >= 4 chars inside merged tokens via the trigram index. Ranked after bm25
    # hits and labelled as such in the evidence.
    long_toks = [t for t in toks if len(t) >= 4]
    if long_toks:
        q = " OR ".join(fts_phrase(t) for t in long_toks)
        rows = repo.query("SELECT d.asset_id, d.norm_text FROM ocr_doc_tri t JOIN ocr_docs d ON d.asset_id=t.asset_id"
                          " WHERE ocr_doc_tri MATCH ? LIMIT ?", (q, limit))
        extra = []
        for r in rows:
            aid = r["asset_id"]
            if aid in found or (eligible is not None and aid not in eligible):
                continue
            hits = [t for t in long_toks if t in r["norm_text"]]
            extra.append((aid, float(len(hits)), True))
        extra.sort(key=lambda x: (-x[1], x[0]))
        out.extend(extra)
    return out


def word_evidence(repo: Repository, asset_id: str, free_text: str, merged: bool) -> list[dict]:
    """Regions containing the query words (only for results actually shown)."""
    toks = tokens(free_text)
    if merged:
        toks = [t for t in toks if len(t) >= 4]
    regs = repo.query("SELECT region_id, raw_text, norm_text, polygon, frame_id, t_s FROM ocr_regions"
                      " WHERE asset_id=? ORDER BY order_idx", (asset_id,))
    ev = []
    for g in regs:
        hit = [t for t in toks if (t in g["norm_text"] if merged else find_occurrences(g["norm_text"], t))]
        if hit:
            ev.append({"region_id": g["region_id"], "polygon": json.loads(g["polygon"]), "excerpt": g["raw_text"],
                       "terms": hit, "merged": merged, "frame_id": g["frame_id"], "t_s": g["t_s"]})
    if any(e["frame_id"] for e in ev):
        # Video: geometry belongs to one keyframe; keep the frame with the most distinct query terms.
        by_frame: dict[str, list[dict]] = {}
        for e in ev:
            by_frame.setdefault(e["frame_id"], []).append(e)
        best = max(by_frame.values(), key=lambda es: (len({t for e in es for t in e["terms"]}), -es[0]["t_s"]))
        ev = best
    return ev[:5]


def annotation_search(repo: Repository, free_text: str, eligible: set[str] | None = None,
                      limit: int = 500) -> list[tuple[str, float]]:
    toks = tokens(free_text)
    if not toks:
        return []
    q = " OR ".join(fts_phrase(t) for t in toks)
    rows = repo.query(
        "SELECT asset_id, bm25(annotation_fts) AS s FROM annotation_fts WHERE annotation_fts MATCH ?"
        " ORDER BY s LIMIT ?", (q, limit))
    return [(r["asset_id"], -float(r["s"])) for r in rows if eligible is None or r["asset_id"] in eligible]
