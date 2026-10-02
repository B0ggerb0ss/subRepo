"""Explicit query grammar -> ParsedQuery.

Grammar (whitespace separated terms):
    term       := filter | phrase | word
    filter     := KEY ":" (WORD | '"' ... '"')
    phrase     := '"' ... '"'            -> same as text:"..."
    KEY        := text | source | object | scene | tag | collection | format
                | type | capture | context | topic | after | before | status

Typed filters are hard constraints combined with AND. Everything else is
free-text intent searched approximately (lexical + semantic channels).
Unknown keys and malformed terms raise ``QueryParseError`` with a usable
message; nothing is ever passed through as SQL or a raw FTS expression.
"""
from __future__ import annotations

import re
from datetime import date

from models.search import Filter, ParsedQuery

KEYS = {
    "text": "literal OCR text (quote multi-word phrases)",
    "source": "screenshot source app: linkedin, youtube, github, whatsapp, instagram, browser, other",
    "object": "detected object label (supported COCO labels)",
    "scene": "scene label: beach, city_street, forest, mountain, office, kitchen, classroom, stadium",
    "tag": "your own tag",
    "collection": "collection key or id",
    "format": "jpeg, png, webp, mp4 or webm",
    "type": "asset type: image or video",
    "capture": "capture type: screenshot, photo, scanned_document, graphic",
    "context": "film_tv_frame, presentation_slide, source_code, job_posting, article, conversation",
    "topic": "hiring, ai_ml, software_development, education, entertainment",
    "after": "imported on/after YYYY-MM-DD",
    "before": "imported before YYYY-MM-DD",
    "status": "analysis status: complete, partial, error, pending",
}
_ALIASES = {"ocr": "text", "app": "source", "obj": "object", "fmt": "format", "col": "collection", "kind": "type"}
_TOKEN = re.compile(r'\s*(?:(-?)([A-Za-z_]+):"((?:[^"\\]|\\.)*)"|(-?)([A-Za-z_]+):(\S+)|"((?:[^"\\]|\\.)*)"|(\S+))')


class QueryParseError(ValueError):
    pass


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def parse_query(raw: str) -> ParsedQuery:
    raw = raw or ""
    if len(raw) > 1000:
        raise QueryParseError("query is too long (max 1000 characters)")
    pos = 0
    words: list[str] = []
    phrases: list[str] = []
    filters: list[Filter] = []
    notes: list[str] = []
    while pos < len(raw):
        if raw[pos:].strip() == "":
            break
        m = _TOKEN.match(raw, pos)
        if not m or m.end() == pos:
            raise QueryParseError(f"could not parse query near: {raw[pos:pos + 20]!r}")
        pos = m.end()
        neg_q, key_q, val_q, neg_w, key_w, val_w, phrase, word = m.groups()
        if key_q or key_w:
            neg = neg_q or neg_w
            key = (key_q or key_w).lower()
            value = _unescape(val_q) if key_q else val_w
            key = _ALIASES.get(key, key)
            if key.startswith("http") or key in {"https", "http", "ftp", "mailto"}:
                words.append(m.group(0).strip())  # a URL, not a filter
                continue
            if key not in KEYS:
                known = ", ".join(sorted(KEYS))
                raise QueryParseError(f"unknown filter '{key}:'. Supported filters: {known}. "
                                      f"Quote the whole term (\"{key}:{value}\") to search it as text.")
            if neg:
                raise QueryParseError("negated filters (-key:) are not supported; exclusions are approximate "
                                      "and must be chosen explicitly")
            if not value.strip():
                raise QueryParseError(f"filter '{key}:' needs a value")
            if key in {"after", "before"}:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise QueryParseError(f"{key}: expects a date like 2026-09-30")
            if key == "text":
                phrases.append(value)
            else:
                filters.append(Filter(key=key, value=value.strip().lower() if key != "tag" else value.strip()))
        elif phrase is not None:
            if phrase.strip():
                phrases.append(_unescape(phrase))
        else:
            words.append(word)
    free = " ".join(words)
    if re.search(r"\b(without|not|no|left of|right of|above|below)\b", free, re.I):
        notes.append("negation and spatial relations in free text are matched approximately, not enforced")
    return ParsedQuery(raw=raw, free_text=free, text_phrases=phrases, filters=filters, approximate_notes=notes)
