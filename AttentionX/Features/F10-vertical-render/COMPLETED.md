# F10 — Vertical Crop and Render — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File                 | Role                                                         |
|----------------------|--------------------------------------------------------------|
| `services/render.py` | `render_vertical_clip()`, `_mean_face_cx()`, `_verify_output()` |
| `utils/ffmpeg_utils.py` | `get_video_dimensions()`, `probe_streams()`, `run_ffmpeg()` |

---

## FFmpeg Steps

```
Step 1: Trim
  ffmpeg -ss {start} -to {end} -i {norm_path} -c copy -y {temp_seg}

Step 2: Crop + captions + transcode
  ffmpeg -i {temp_seg}
         -vf "crop={crop_w}:{crop_h}:{crop_x}:0,subtitles={srt_abs}"
         -c:v libx264 -preset fast -crf 23
         -c:a aac -b:a 128k
         -movflags +faststart
         -y {output}
```

## Crop Logic

```
crop_w = H * 9 / 16          # target 9:16 width from source height
crop_h = H                   # full height
cx     = mean face center X in window (fallback: 0.5)
crop_x = clamp(cx_px - crop_w/2, 0, W - crop_w)
```

## Implementation Notes

- SRT path resolved to absolute before passing to `subtitles=` filter — relative paths unreliable in FFmpeg subtitles filter
- `_mean_face_cx` filters out 0.5 fallback values using epsilon (`abs(cx-0.5) > 1e-6`) to avoid biasing crop toward center when face was detected
- `_verify_output` checks that `w * 16 == h * 9` — catches sub-pixel rounding errors in crop dimensions
- All FFmpeg calls go through `run_ffmpeg()` — no direct subprocess in this file

## Deviations from IMPL.md

- Float equality `cx != 0.5` in `_mean_face_cx` replaced with epsilon comparison (linter compliance)
- `_verify_output` uses `streams.get("streams", [])` defensive access instead of `streams["streams"]` direct access

---

## Gate 10 Criteria (pending live render test)

```
Output is 9:16 aspect ratio                → _verify_output: w*16 == h*9
RenderError raised on bad stream           → _verify_output raises RenderError
Face-aware crop applied                    → _mean_face_cx() drives crop_x
SRT captions burned in                     → subtitles= vf filter
shell=False enforced                       → via run_ffmpeg() wrapper
Returns absolute path to output clip       → str(output.resolve())
```
