# F12 — Reference Style Replication — Validation

## Validation Context

F12 is optional. Gate 7 pass criteria do not require F12 to be present.
F12 validation verifies it improves ranking without breaking the pipeline.

## Pass Criteria

```
StyleProfile returned for valid reference clips             ✓
StyleProfile is None when ref_paths is empty or None       ✓
Broken reference clip skipped silently (no exception)      ✓
Pipeline completes without style_profile (F08 handles None) ✓
style_score in [0, 1] when profile is provided             ✓
```

## Test Cases

### TC-01: Single reference clip

```
Input:    one valid 30-second reference short clip
Expected: StyleProfile returned
          mean_duration ≈ 30.0
          mean_face_ratio in [0.0, 1.0]
          mean_caption_density > 0.0
```

### TC-02: Empty reference list

```
Input:    ref_paths = []
Expected: None returned
          No exception raised
```

### TC-03: Mixed valid/invalid reference clips

```
Input:    [valid_clip.mp4, corrupt_file.mp4, valid_clip2.mp4]
Expected: StyleProfile computed from the 2 valid clips
          Corrupt file skipped silently
          No exception raised
```

### TC-04: Style score effect on ranking

```
Input:    candidates where one matches the reference style closely
Expected: style_score for the matching candidate is higher than for a dissimilar one
          final_score of the matching candidate increases by approximately weight * style_score
```

### TC-05: Pipeline without F12

```
Input:    run full pipeline with ref_clips=None
Expected: style_profile=None passed to score_candidates
          All style_scores = 0.0
          Pipeline completes normally
          Ranked results returned
```

## Manual Verification

- [ ] Upload 2–3 reference short clips via the UI
- [ ] Confirm pipeline completes without error
- [ ] Print style_profile fields — confirm values are plausible
- [ ] Compare top-ranked clips with and without reference — check if reference biases selection
