# F01 — Input Normalization

## Purpose

Accept any uploaded video file and transcode it into a known-good MP4/H.264 format
before any downstream analysis or rendering stage touches it.

This is the single most important pre-condition for deterministic pipeline behavior.
Codec chaos downstream is eliminated by enforcing a standard format at the boundary.

## Inputs

| Name         | Type       | Description                              |
|--------------|------------|------------------------------------------|
| input_path   | str        | Absolute path to the uploaded video file |

## Outputs

| Name          | Type | Description                              |
|---------------|------|------------------------------------------|
| norm_path     | str  | Absolute path to `output_norm.mp4`       |

Output location: `data/temp/{session_id}/output_norm.mp4`

## Behavior

1. Accept `input_path` from the UI layer.
2. Run FFmpeg transcode to H.264/AAC MP4.
3. Verify output file exists and has both video and audio streams via ffprobe.
4. Return `norm_path` on success; raise `NormalizationError` on failure.

## FFmpeg Command

```bash
ffmpeg -i {input_path} \
       -c:v libx264 -preset fast -crf 23 \
       -c:a aac -b:a 128k \
       -movflags +faststart \
       -y {norm_path}
```

`-movflags +faststart` ensures the MP4 moov atom is at the front for browser streaming.

## Error Handling

- FFmpeg non-zero exit → raise `NormalizationError` with stderr content
- Output file missing after FFmpeg exit 0 → raise `NormalizationError`
- ffprobe reports no video stream → raise `NormalizationError`

## Constraints

- Must run before any other pipeline stage.
- Input format may be any container (MP4, MOV, MKV, AVI, WebM).
- Output must always be H.264 + AAC in MP4 container.
- Temp files written to `data/temp/` only.
