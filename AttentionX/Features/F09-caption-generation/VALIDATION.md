# F09 — Caption Generation — Validation

## Gate 8 Pass Criteria

```
SRT file created at expected path                           ✓
Timestamps in correct SRT format (HH:MM:SS,mmm)            ✓
No overlapping time ranges                                  ✓
All lines <= 42 characters                                  ✓
No more than 2 lines per subtitle block                     ✓
Timestamps are relative to clip start (not source start)   ✓
FFmpeg subtitle filter accepts the SRT without error        ✓
```

## Test Cases

### TC-01: Normal transcript window

```
Input:    5 TranscriptSegment objects covering 0–15 seconds
Expected: SRT file with 5 blocks
          Block 1 starts at 00:00:00,000
          Timestamps increase monotonically
```

### TC-02: Relative timestamp offset

```
Input:    segment at source time 45.2–48.7s, clip_start=45.0
Expected: SRT block shows 00:00:00,200 --> 00:00:03,700
          NOT 00:00:45,200
```

### TC-03: Long text wrapping

```
Input:    segment text = "This is a very long sentence that is definitely over forty-two chars"
Expected: text wrapped into 2 lines, each <= 42 chars
          Block has exactly 2 lines (not 3)
```

### TC-04: Empty transcript

```
Input:    transcript_segs = []
Expected: SRT file created but empty (0 bytes or just whitespace)
          No exception raised
```

### TC-05: FFmpeg compatibility

```
Input:    generated clip_0.srt
Command:  ffmpeg -i clip.mp4 -vf subtitles=clip_0.srt -y test_out.mp4
Expected: FFmpeg exits with returncode 0
          Captions visible in test_out.mp4
```

### TC-06: Time format correctness

```
Input:    seconds = 3723.456
Expected: _fmt_time(3723.456) == "01:02:03,456"
```

## Manual Verification

- [ ] Open generated SRT in a text editor — confirm block structure is correct
- [ ] Play rendered clip — confirm captions appear and are time-aligned
- [ ] Spot-check 2–3 caption blocks against source transcript
- [ ] Confirm no line exceeds 42 characters (count manually or grep)
