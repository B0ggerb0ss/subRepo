# F09 — Caption Generation

## Purpose

Generate a properly formatted SRT subtitle file for each selected clip window.
The SRT file is consumed by FFmpeg in F10 to burn captions into the rendered video.

## Inputs

| Name         | Type                     | Description                          |
|--------------|--------------------------|--------------------------------------|
| scored_seg   | ScoredSegment            | Selected clip with transcript_segs   |
| clip_index   | int                      | Index for output filename (0, 1, 2)  |
| output_dir   | str                      | Temp directory for SRT files         |

## Outputs

| Name      | Type | Description                          |
|-----------|------|--------------------------------------|
| srt_path  | str  | Absolute path to `clip_N.srt` file   |

## SRT Format

```
1
00:00:00,000 --> 00:00:03,200
First line of caption text here

2
00:00:03,200 --> 00:00:06,800
Second line continues here
```

Rules:
- Timestamps relative to clip start (not source video start).
- Each block: index (1-based), timecodes, text, blank line separator.
- Maximum line length: 42 characters.
- Maximum 2 lines per subtitle block.
- No overlapping time ranges.
- Milliseconds separated by comma (not period).

## Behavior

1. Receive `scored_seg.candidate.transcript_segs` and clip `start` time.
2. For each `TranscriptSegment` in the window:
   a. Compute relative times: `rel_start = seg.start - clip_start`, `rel_end = seg.end - clip_start`.
   b. Wrap text to ≤ 42 characters per line, ≤ 2 lines per block.
   c. Format SRT block.
3. Write SRT file to `output_dir/clip_{clip_index}.srt`.
4. Return `srt_path`.

## Error Handling

- If `transcript_segs` is empty → write SRT with no blocks (valid empty SRT).
- Overlapping relative timestamps → clamp end to next segment's start.
- Line wrapping failure → truncate at 42 characters (never silently drop text).

## Constraints

- Timestamps must be relative to clip start, not source video start.
- Must produce valid SRT parseable by FFmpeg's subtitle filter.
- Write to `data/temp/` only.
