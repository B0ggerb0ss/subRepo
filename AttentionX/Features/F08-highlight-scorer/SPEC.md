# F08 — Highlight Scorer

## Purpose

Rank candidate segments (from F07) using a weighted multisignal formula.
Return the top N candidates with per-feature score breakdowns for explainability.
The output determines which clips get rendered (F10) and displayed in the UI (F11).

## Inputs

| Name            | Type                    | Description                         |
|-----------------|-------------------------|-------------------------------------|
| candidates      | list[CandidateSegment]  | From F07                            |
| top_n           | int                     | Number of clips to return (default: 3) |
| style_profile   | StyleProfile or None    | Optional, from F12                  |

## Outputs

| Name        | Type                | Description                              |
|-------------|---------------------|------------------------------------------|
| ranked      | list[ScoredSegment] | Top N candidates sorted by score desc    |

## Data Schema

```python
@dataclass
class ScoredSegment:
    candidate:          CandidateSegment
    final_score:        float            # weighted sum [0, 1]
    transcript_score:   float            # hook quality [0, 1]
    energy_score:       float            # from candidate.energy_score
    face_score:         float            # from candidate.face_score
    scene_score:        float            # from candidate.scene_score
    style_score:        float            # from style_profile match [0, 1]; 0 if no profile
    score_breakdown:    dict[str, float] # for UI display
```

## Scoring Formula

```
final_score = (
    transcript_score * 0.30 +
    energy_score     * 0.25 +
    face_score       * 0.25 +
    scene_score      * 0.10 +
    style_score      * 0.10
)
```

Weights are defined in `Settings` and are configurable without code changes.

## Transcript Hook Quality

The `transcript_score` is derived from simple heuristics on `candidate.transcript_text`:
- Question presence: +0.2
- Imperative openers ("you need", "here's", "the reason"): +0.2
- Length in 40–120 word range: +0.2
- Absence of filler-heavy openings ("um", "uh", "like" at ratio > 0.1): +0.2
- Capitalized proper nouns or numbers (suggests concrete content): +0.2

Score is the sum of triggered heuristics, capped at 1.0.

## Style Score (optional)

If `style_profile` is provided (from F12):
- Compare candidate duration to profile mean duration → similarity score
- Compare face_score to profile mean face ratio → similarity score
- Average the two → style_score

If no `style_profile` → `style_score = 0.0`.
The weight (0.10) is small enough that absence does not significantly affect ranking.

## Constraints

- Return exactly `top_n` results if available; fewer if candidates < top_n.
- Never return an empty list (at least 1 candidate is guaranteed from F07).
- All score fields must be in [0.0, 1.0].
- `score_breakdown` must be populated for every returned segment (required by UI).
