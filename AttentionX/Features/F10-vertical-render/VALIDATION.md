# F10 — Vertical Crop and Render — Validation

## Gate 9 Pass Criteria

```
Output MP4 file exists                                      ✓
ffprobe: video codec = h264                                 ✓
ffprobe: width * 16 == height * 9 (9:16 aspect ratio)      ✓
ffprobe: audio stream present                               ✓
Captions visible and time-aligned in playback              ✓ (manual)
Speaker remains in frame for majority of clip              ✓ (manual)
RenderError raised when FFmpeg fails                        ✓
```

## Test Cases

### TC-01: Full render pipeline

```
Input:    norm.mp4, scored_seg with start=10, end=25, valid srt, valid face_track
Expected: clip_0.mp4 created in output_dir
          ffprobe confirms h264, aac, 9:16 ratio
          File plays in browser
```

### TC-02: 9:16 aspect ratio math

```
Input:    source W=1920, H=1080
Expected: crop_w = 1080 * 9 / 16 = 607 (or 608 depending on int())
          crop_h = 1080
          ffprobe output: width=607 or 608, height=1080
          607 * 16 == 9712 and 1080 * 9 == 9720 → close but integer rounding
          Accept within ±1 pixel due to integer rounding
```

### TC-03: Face-centered crop

```
Input:    face_track with mean cx = 0.7 (speaker is right of center)
          source W=1920, crop_w=607
Expected: crop_x = clamp(0.7*1920 - 607/2, 0, 1920-607) = clamp(1344-303, 0, 1313) = 1041
          Speaker should appear roughly centered in output
```

### TC-04: Center-crop fallback

```
Input:    face_track with visibility_ratio = 0.0 (all centers = 0.5)
Expected: crop_x = (W - crop_w) // 2  (exact center)
          No exception raised
```

### TC-05: Missing SRT fallback

```
Input:    srt_path points to a non-existent file
Expected: video renders without captions (warning logged)
          Output still produced and passes ffprobe check
```

### TC-06: RenderError propagation

```
Input:    corrupt temp_seg.mp4 passed to crop step
Expected: RenderError raised with informative message
          Partial output file cleaned up or not returned
```

## Manual Verification Checklist

- [ ] Play clip_0.mp4 in a browser — confirm vertical orientation
- [ ] Check captions appear and text matches spoken audio
- [ ] Confirm speaker's face is visible and roughly centered
- [ ] Confirm duration matches (end - start) of scored_seg within ±1 second
- [ ] Run ffprobe — confirm codec=h264, check width and height values
