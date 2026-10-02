# F08 — Highlight Scorer — Validation

## Gate 7 Pass Criteria

```
Ranked list returned with >= 1 ScoredSegment                ✓
All final_score values in [0.0, 1.0]                        ✓
List sorted descending by final_score                        ✓
Per-feature scores present in score_breakdown               ✓
Weights sum to 1.0 (Settings.score_weights validation)      ✓
Top segment appears reasonable on manual review             ✓ (manual)
```

## Test Cases

### TC-01: Ranking order

```
Input:    3 candidates with known signal values
Expected: candidate with highest weighted sum ranked first
          Compute expected final_score manually and compare
```

### TC-02: Weights sum to 1.0

```
Input:    Settings.score_weights dict
Expected: sum(Settings.score_weights.values()) == 1.0
```

### TC-03: Score clamping

```
Input:    a candidate where the weighted sum would exceed 1.0
Expected: final_score = 1.0 (clamped, not > 1.0)
```

### TC-04: Style score absent

```
Input:    candidates, style_profile=None
Expected: style_score = 0.0 for all segments
          final_score still computed using remaining weights
```

### TC-05: top_n limit

```
Input:    10 candidates, top_n=3
Expected: exactly 3 ScoredSegments returned
          They are the 3 highest-scoring candidates
```

### TC-06: transcript_score heuristics

```
Input:    text with a question mark and an imperative opener
Expected: transcript_score >= 0.4
Input:    text with 80% filler words and no question
Expected: transcript_score <= 0.2
```

### TC-07: score_breakdown completeness

```
Input:    any candidate list
Expected: each ScoredSegment.score_breakdown contains keys:
          "transcript", "energy", "face", "scene", "style", "final"
```

## Manual Review Checklist

- [ ] Print top 3 segments with all score fields
- [ ] Watch source video at top-ranked segment timestamps
- [ ] Confirm the top clip appears genuinely more interesting than the bottom clip
- [ ] Confirm score_breakdown values are all floats in [0, 1]
- [ ] Confirm weights in Settings sum to 1.0
