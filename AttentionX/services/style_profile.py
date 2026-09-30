"""F12 — Reference Style Replication (stub)

Full implementation: Features/F12-style-replication/IMPL.md

Optional feature. Returns None when not implemented so scorer
treats style_score as 0.0 for all candidates.
"""
from __future__ import annotations

from models.schemas import StyleProfile


def build_style_profile(ref_paths: list[str]) -> StyleProfile | None:
    return None
