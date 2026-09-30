# F07 — Candidate Segment Builder — Validation

## Gate 7 Contribution

F07 must produce candidates before F08 can score them.

## Pass Criteria

```
At least 1 CandidateSegment returned                       ✓
All candidates: 5.0 <= duration <= 20.0                    ✓
No overlapping windows (end[i] <= start[i+1])              ✓
All windows within [0, video_duration]                     ✓
energy_score, face_score, scene_score all in [0, 1]        ✓
transcript_text non-empty for speech-containing windows    ✓
```

## Test Cases

### TC-01: Normal transcript chunking

```
Input:    30 transcript segments spanning 120 seconds
Expected: 6–12 candidate windows
          Each duration between 5 and 20 seconds
          No gaps or overlaps
```

### TC-02: Very short video (< 10 seconds of transcript)

```
Input:    transcript covering 8 seconds of audio
Expected: 1 candidate returned covering the full transcript
          duration >= 5.0 (or the full duration if less)
```

### TC-03: Scene snap behavior

```
Input:    candidate start=12.7, scene_boundaries=[12.0, 25.0], tolerance=1.0
Expected: candidate.start snapped to 12.0 (within tolerance)
```

### TC-04: Scene snap miss

```
Input:    candidate start=12.7, scene_boundaries=[10.0, 25.0], tolerance=1.0
Expected: candidate.start = 12.7 (no snap; nearest boundary is 2.7s away)
```

### TC-05: Scene coherence scoring

```
Input:    window [10, 30], scene_boundaries=[15, 20, 25]  (3 internal cuts)
Expected: scene_score = 1 / (1 + 3) = 0.25
```

### TC-06: Fallback candidate

```
Input:    empty transcript, video_duration=60.0
Expected: 1 candidate returned covering roughly the middle 15 seconds
          No exception raised
```

## Manual Review

- [ ] Print all candidates with start, end, duration, energy_score, face_score, scene_score
- [ ] Verify no two candidates overlap
- [ ] Verify all durations in [5, 20] seconds
- [ ] Spot-check: high face_score candidates should be talking-head moments in the source video
