# F08 — Highlight Scorer — Implementation

## File Location

`services/scorer.py`

## Dependencies

- `models/schemas.py` — `CandidateSegment`, `ScoredSegment`, `StyleProfile`
- `models/settings.py` — `Settings.score_weights`, `Settings.top_n_clips`

## Core Function Signature

```python
def score_candidates(
    candidates: list[CandidateSegment],
    top_n: int = 3,
    style_profile: StyleProfile | None = None,
) -> list[ScoredSegment]:
```

## Implementation

```python
def score_candidates(candidates, top_n=3, style_profile=None):
    scored = []
    for c in candidates:
        t_score = _transcript_score(c.transcript_text)
        s_score = _style_score(c, style_profile) if style_profile else 0.0
        
        weights = Settings.score_weights   # dict with keys matching score names
        final = (
            t_score   * weights["transcript"] +
            c.energy_score * weights["energy"]     +
            c.face_score   * weights["face"]       +
            c.scene_score  * weights["scene"]      +
            s_score        * weights["style"]
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
```

## Transcript Hook Heuristics

```python
import re

IMPERATIVE_PATTERNS = [
    r"\byou need\b", r"\bhere'?s\b", r"\bthe reason\b",
    r"\bwhat if\b", r"\bstop\b", r"\bwait\b"
]
FILLER_WORDS = ["um", "uh", "like", "you know"]

def _transcript_score(text: str) -> float:
    text_lower = text.lower()
    words = text_lower.split()
    score = 0.0
    if "?" in text:                                        score += 0.2
    if any(re.search(p, text_lower) for p in IMPERATIVE_PATTERNS): score += 0.2
    if 40 <= len(words) <= 120:                            score += 0.2
    filler_count = sum(words.count(f) for f in FILLER_WORDS)
    if len(words) > 0 and filler_count / len(words) <= 0.1: score += 0.2
    if re.search(r"\b[A-Z][a-zA-Z]+\b|\b\d+\b", text):   score += 0.2
    return min(1.0, score)
```

## Settings

```python
class Settings:
    score_weights: dict = {
        "transcript": 0.30,
        "energy":     0.25,
        "face":       0.25,
        "scene":      0.10,
        "style":      0.10,
    }
    top_n_clips: int = 3
```

## Notes

- `_transcript_score` is a heuristic, not ML. Simple, fast, adjustable.
- Weights live in `Settings` so they can be tuned without touching scorer logic.
- `round(..., 4)` prevents floating-point display noise in the UI.
