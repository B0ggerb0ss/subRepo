# F10 — Vertical Crop and Render

## Purpose

Produce the final browser-playable 9:16 vertical MP4 for each top-ranked clip.
Combines: timeline trimming, face-aware 9:16 crop, SRT caption burn-in, and H.264 export.

## Inputs

| Name         | Type          | Description                                  |
|--------------|---------------|----------------------------------------------|
| norm_path    | str           | Path to normalized source MP4 (F01)          |
| scored_seg   | ScoredSegment | Selected clip with start/end times           |
| srt_path     | str           | Path to SRT caption file (F09)               |
| face_track   | FaceTrack     | Face center coordinates (F05)                |
| clip_index   | int           | Output filename index (0, 1, 2)              |
| output_dir   | str           | Final output directory                       |

## Outputs

| Name        | Type | Description                               |
|-------------|------|-------------------------------------------|
| output_path | str  | Absolute path to `clip_N.mp4`             |

## Pipeline Steps (in order, each a discrete FFmpeg call)

### Step 1 — Trim segment

```bash
ffmpeg -ss {start} -to {end} -i {norm_path} -c copy -y {temp_segment.mp4}
```

`-c copy` for speed; re-encoding happens in the crop step.

### Step 2 — Compute crop window

```
source dimensions:  W x H  (from ffprobe on norm_path)
target aspect:      9:16

crop_h = H                          (full source height)
crop_w = int(H * 9 / 16)
face_cx_px = face_cx_normalized * W
crop_x = clamp(face_cx_px - crop_w // 2, 0, W - crop_w)
crop_y = 0
```

If no face (`face_track.visibility_ratio == 0`): `crop_x = (W - crop_w) // 2` (center crop).

### Step 3 — Crop, caption burn-in, and export

```bash
ffmpeg -i {temp_segment.mp4} \
       -vf "crop={crop_w}:{crop_h}:{crop_x}:{crop_y},
            subtitles={srt_path}" \
       -c:v libx264 -preset fast -crf 23 \
       -c:a aac -b:a 128k \
       -movflags +faststart \
       -y {output_path}
```

### Step 4 — Verify output

Run `ffprobe` on `output_path`:
- video stream codec = h264
- width * 16 == height * 9 (aspect ratio check)
- audio stream present

## Face Center for Crop

Use the mean of `face_track.centers_x` for frames in `[start, end]` range as the crop anchor.
This produces a stable horizontal crop rather than a jittery per-frame crop.

## Error Handling

- FFmpeg trim failure → raise `RenderError`
- FFmpeg crop/export failure → raise `RenderError` with stderr
- ffprobe fails aspect ratio check → raise `RenderError("output not 9:16")`
- SRT file missing → render without subtitles (fallback; log warning)

## Constraints

- All FFmpeg calls use `shell=False`.
- Output must be H.264 MP4, browser-playable.
- Output written to `data/outputs/`.
- Temp segment written to `data/temp/`.
- Verify with ffprobe before returning path to UI.
