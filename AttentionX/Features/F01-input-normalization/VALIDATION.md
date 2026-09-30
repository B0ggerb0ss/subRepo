# F01 — Input Normalization — Validation

## Gate 2 Contribution

This feature is one of two that must pass before Gate 2 closes.

## Test Cases

### TC-01: Happy path — standard MP4 upload

```
Input:    any valid MP4 with audio
Expected: output_norm.mp4 exists
          ffprobe → codec_name: h264
          ffprobe → audio stream present
          normalize_video() returns path string without raising
```

### TC-02: Non-MP4 input (MOV, MKV, AVI, WebM)

```
Input:    a .mov or .mkv file
Expected: same as TC-01 — output is always MP4/H.264
```

### TC-03: Input file with no audio track

```
Input:    a video file with video only (no audio)
Expected: NormalizationError raised with message indicating missing audio
          OR: silent audio track added (decide in implementation and document here)
```

### TC-04: Corrupt or unreadable input

```
Input:    a file with .mp4 extension but invalid content
Expected: NormalizationError raised, stderr logged
          No partial output file left on disk
```

### TC-05: FFmpeg not installed

```
Input:    any valid MP4
Expected: NormalizationError raised with clear message about missing ffmpeg
          Not a raw FileNotFoundError that leaks internal paths
```

## Manual Verification Steps

1. Upload a 30–60 second MP4 to the app.
2. Confirm `data/temp/{session}/output_norm.mp4` is created.
3. Open the file in a browser or media player — confirm playback.
4. Run `ffprobe output_norm.mp4` — confirm h264 video and aac audio.
5. Check that `-movflags +faststart` is effective: moov atom appears before mdat
   (use `ffprobe -v trace output_norm.mp4 2>&1 | grep -E "moov|mdat"` and verify moov first).

## Pass Criteria Summary

```
output_norm.mp4 exists                            ✓
ffprobe: video stream codec = h264                ✓
ffprobe: audio stream present                     ✓
normalize_video() returns path, no exception      ✓
NormalizationError raised on bad input            ✓
shell=False used in subprocess call               ✓ (code review)
```
