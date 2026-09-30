# F11 — Gradio UI — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File     | Role                                              |
|----------|---------------------------------------------------|
| `app.py` | Full pipeline wiring + Gradio UI — full implementation |

---

## Pipeline Call Order in `run_pipeline()`

```
1. normalize_video(long_video_path, temp_dir)          → norm_path
2. extract_audio(norm_path, temp_dir)                  → wav_path
3. transcribe(wav_path, model_size)                    → transcript
4. analyze_audio_energy(wav_path, percentile, merge_gap) → energy_peaks, _
5. track_faces(norm_path, sample_fps)                  → face_track
6. detect_scenes(norm_path, threshold)                 → scene_boundaries
7. get_duration(norm_path)                             → video_duration
8. build_candidates(transcript, energy_peaks, face_track,
                    scene_boundaries, video_duration, ...)  → candidates
9. build_style_profile(ref_clips)  [if ref_clips]      → style_profile | None
10. score_candidates(candidates, top_n, style_profile) → ranked
11. for each ranked seg:
      generate_srt(seg, i, temp_dir)                   → srt_path
      render_vertical_clip(norm_path, seg, srt_path,
                           face_track, i, temp_dir, output_dir) → clip_path
```

## Session Isolation

Each call gets `uuid.uuid4().hex` — temp and output go to separate `data/temp/{id}/` and `data/outputs/{id}/` directories. No cross-session file collisions.

## UI Components

| Component       | Type       | Purpose                        |
|-----------------|------------|--------------------------------|
| `long_video`    | gr.Video   | Upload source video            |
| `ref_clips_input` | gr.File  | Optional reference short clips |
| `generate_btn`  | gr.Button  | Trigger pipeline               |
| `clip1/2/3`     | gr.Video   | Output preview (up to 3)       |
| `download_files`| gr.Files   | Batch download                 |
| `status_box`    | gr.Textbox | Pipeline status / errors       |

## Deviations from IMPL.md

- IMPL.md used `Settings.top_n_clips` class-level access. Fixed to `settings.top_n_clips` (module singleton).
- IMPL.md had `outputs=[*clip_outputs[:1], download_files, status_box]` — only bound 1 clip output. Fixed to bind all 3: `outputs=[clip1, clip2, clip3, download_files, status_box]`.
- `run_pipeline` returns explicit 5-tuple `(clip1, clip2, clip3, download_files, status)` with `None` padding for unused clip slots.
- All Settings parameters passed explicitly from `settings` instance rather than using defaults, ensuring Settings singleton is the single source of truth.

---

## Integration Verified

```
All 16 service/utility modules import cleanly    → python import check: 16/16 OK
All pipeline function signatures match call sites → signature check: 11/11 OK
Gate 1: 7/7 PASS
```
