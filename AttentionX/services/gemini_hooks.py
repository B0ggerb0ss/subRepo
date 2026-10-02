"""F13 — Gemini Hook Generation (stub)

Full implementation: Features/F13-gemini-hooks/IMPL.md

This feature is optional and gated by GEMINI_API_KEY env var.
The stub returns empty strings so the pipeline runs without it.
"""
from __future__ import annotations

from models.schemas import ScoredSegment


def generate_hook(scored_seg: ScoredSegment, clip_index: int) -> tuple[str, str]:
    """Return (hook_text, summary). Returns ('', '') until F13 is implemented."""
    return "", ""
