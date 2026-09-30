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
        "SELECT region_id, raw_text, char_start, char_end, polygon FROM ocr_regions WHERE asset_id=?"
        " ORDER BY order_idx", (asset_id,))
    matches = []
    for s, e in spans:
        regs = [r for r in rows if r["char_start"] < e and r["char_end"] > s]
        matches.append({
            "span": (s, e),
            "region_ids": [r["region_id"] for r in regs],
            "polygons": [json.loads(r["polygon"]) for r in regs],
            "excerpt": " / ".join(r["raw_text"] for r in regs),
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
            out[r["asset_id"]] = _regions_for_spans(repo, r["asset_id"], spans)
    return out


_WORD = re.compile(r"[\w+#][\w+#.\-/$%]*", re.UNICODE)


def tokens(text: str) -> list[str]:
    norm = normalize_for_search(text)
    return [t.strip(".-/") for t in _WORD.findall(norm) if t.strip(".-/")]


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
        regs = repo.query("SELECT region_id, raw_text, norm_text, polygon FROM ocr_regions WHERE asset_id=?"
                          " ORDER BY order_idx", (r["asset_id"],))
        ev = []
        for reg in regs:
            hit = [t for t in toks if find_occurrences(reg["norm_text"], t)]
            if hit:
                ev.append({"region_id": reg["region_id"], "polygon": json.loads(reg["polygon"]),
                           "excerpt": reg["raw_text"], "terms": hit})
        # bm25() is "lower is better"; expose the positive magnitude.
        out.append((r["asset_id"], -float(r["s"]), ev[:5]))
    return out


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
