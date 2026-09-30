"""F08 — Highlight Scorer

Spec reference: Features/F08-highlight-scorer/SPEC.md
"""
from __future__ import annotations

import re

from models.schemas import CandidateSegment, ScoredSegment, StyleProfile
from models.settings import settings

_IMPERATIVE_PATTERNS = [
    r"\byou need\b", r"\bhere'?s\b", r"\bthe reason\b",
    r"\bwhat if\b", r"\bstop\b", r"\bwait\b",
]
_FILLER_WORDS = ["um", "uh", "like", "you know"]


def score_candidates(
    candidates: list[CandidateSegment],
    top_n: int = 3,
    style_profile: StyleProfile | None = None,
) -> list[ScoredSegment]:
    """Score candidates and return top_n sorted by final_score descending."""
    weights = settings.score_weights
    scored: list[ScoredSegment] = []

    for c in candidates:
        t_score = _transcript_score(c.transcript_text)
        s_score = _style_score(c, style_profile) if style_profile else 0.0

        final = (
            t_score        * weights["transcript"]
            + c.energy_score * weights["energy"]
            + c.face_score   * weights["face"]
            + c.scene_score  * weights["scene"]
            + s_score        * weights["style"]
        )
        scored.append(ScoredSegment(
            candidate=c,
            final_score=round(min(1.0, final), 4),
            transcript_score=t_score,
            energy_score=c.energy_score,
            face_score=c.face_score,
            scene_score=c.scene_score,
            style_score=s_score,
            score_breakdown={
                "transcript": t_score,
                "energy": c.energy_score,
                "face": c.face_score,
                "scene": c.scene_score,
                "style": s_score,
                "final": final,
            },
        ))

    scored.sort(key=lambda s: s.final_score, reverse=True)
    return scored[:top_n]


def _transcript_score(text: str) -> float:
    text_lower = text.lower()
    words = text_lower.split()
    score = 0.0
    if "?" in text:
        score += 0.2
    if any(re.search(p, text_lower) for p in _IMPERATIVE_PATTERNS):
        score += 0.2
    if 40 <= len(words) <= 120:
        score += 0.2
    filler_count = sum(words.count(f) for f in _FILLER_WORDS)
    if words and filler_count / len(words) <= 0.1:
        score += 0.2
    if re.search(r"\b[A-Z][a-zA-Z]+\b|\b\d+\b", text):
        score += 0.2
    return min(1.0, score)


def _style_score(c: CandidateSegment, profile: StyleProfile) -> float:
    dur_delta = abs(c.duration - profile.mean_duration) / max(profile.mean_duration, 1.0)
    face_delta = abs(c.face_score - profile.mean_face_ratio)
    return max(0.0, 1.0 - (dur_delta + face_delta) / 2)
