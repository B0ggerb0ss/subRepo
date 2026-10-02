# F05 — Face Detection and Tracking — Validation

## Gate 5 Pass Criteria

```
FaceTrack returned without exception               ✓
len(frame_times) > 0                              ✓
len(centers_x) == len(centers_y) == len(frame_times) ✓
visibility_ratio in [0.0, 1.0]                    ✓
stability_score in [0.0, 1.0]                     ✓
Fallback (0.5, 0.5) used on no-face frames        ✓
Zero-face clip: no exception, visibility_ratio=0  ✓
```

## Test Cases

### TC-01: Talking-head clip with clear speaker

```
Input:    norm.mp4 with a single speaker clearly visible
Expected: visibility_ratio > 0.7
          center_x values cluster around speaker position (not 0.5)
          stability_score > 0.5
```

### TC-02: No-face clip (e.g., screen recording or b-roll)

```
Input:    norm.mp4 with no human faces
Expected: FaceTrack returned (no exception)
          all centers_x = 0.5, all centers_y = 0.5
          visibility_ratio = 0.0
```

### TC-03: Mixed clip (speaker appears partway through)

```
Input:    norm.mp4 where speaker enters at ~30% of duration
Expected: visibility_ratio between 0.1 and 0.9
          centers_x = 0.5 for early frames, non-0.5 for later frames
```

### TC-04: Sampling rate

```
Input:    60-second norm.mp4, sample_fps=2.0
Expected: len(frame_times) approximately 120 (60s * 2fps)
          frame_times[-1] approximately 60.0
```

### TC-05: Resource cleanup

```
Input:    any norm.mp4
Expected: cv2.VideoCapture is released after track_faces() returns
          MediaPipe detector.close() called
          No file handles left open
```

## Manual Verification

- [ ] Print first 10 (time, cx, cy) rows — cx should reflect speaker position in frame
- [ ] For a known talking-head video, confirm visibility_ratio > 0.7
- [ ] Confirm fallback path tested with a video containing no faces
- [ ] Confirm centers_x range is roughly consistent with speaker's horizontal position
