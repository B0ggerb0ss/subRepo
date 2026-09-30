# F06 — Scene Detection — Validation

## Gate 6 Pass Criteria

```
Non-empty list returned (at minimum [0.0])                 ✓
All timestamps are floats >= 0.0                           ✓
Timestamps sorted ascending                                ✓
Detected cuts align with visible shot changes (manual)     ✓
Single-scene video returns [0.0] without exception         ✓
```

## Test Cases

### TC-01: Video with known visual cuts

```
Input:    norm.mp4 with 3+ obvious scene changes (different shots)
Expected: len(scene_boundaries) >= 3
          Timestamps roughly align with visual cut points (within 1 second)
```

### TC-02: Continuous talking-head footage (no cuts)

```
Input:    norm.mp4 with a single uncut shot
Expected: scene_boundaries = [0.0]  or very few false positives
          False positive rate < 1 per 10 seconds of footage
```

### TC-03: Return type and ordering

```
Input:    any norm.mp4
Expected: return value is list[float]
          sorted(result) == result
          all(t >= 0.0 for t in result)
```

### TC-04: Threshold sensitivity

```
Input:    same norm.mp4, threshold=15 vs threshold=40
Expected: threshold=15 produces more detected scenes
          threshold=40 produces fewer detected scenes
          Relationship is monotonic
```

## Manual Verification

- [ ] Print scene boundaries for a test video
- [ ] Seek to each timestamp in a media player — confirm visible cut point nearby
- [ ] Count false positives in a 2-minute talking-head clip — should be < 12
- [ ] Confirm no exception on a video shorter than 5 seconds
