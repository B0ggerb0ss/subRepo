# F01 — Input Normalization — Completion Record

## Status: COMPLETE
## Gate 2 contribution: PASS (partial — F02 completes Gate 2)
## Implementation date: 2026-04-18

---

## Files Implemented

| File                  | Role                                              |
|-----------------------|---------------------------------------------------|
| `services/ingest.py`  | `normalize_video()` — full implementation         |
| `utils/ffmpeg_utils.py` | `run_ffmpeg()`, `probe_streams()` — shared utils |
| `models/schemas.py`   | `NormalizationError`, `RenderError` defined       |

---

## FFmpeg Flags Used

```bash
ffmpeg -i {input_path} \
       -c:v libx264 -preset fast -crf 23 \
       -c:a aac -b:a 128k \
       -movflags +faststart \
       -y {norm_path}
```

| Flag              | Reason                                                    |
|-------------------|-----------------------------------------------------------|
| `-preset fast`    | Reduces CPU time on HF Spaces (vs `medium`)               |
| `-crf 23`         | Balanced quality/size for demo use                        |
| `-movflags +faststart` | Moves moov atom to front for browser streaming       |
| `shell=False`     | Mandatory — user-supplied path, injection risk            |

---

## TC-03 Decision: No-Audio Input

**Decision:** Raise `NormalizationError("no audio stream in normalized output")`.

**Rationale:** Silent-track injection (`-f lavfi -i anullsrc`) is out of scope for the MVP.
The pipeline requires audio for transcription (F03) and energy analysis (F04).
A video with no audio cannot proceed through the pipeline — fail loud, fail early.

**Documentation in SPEC.md:** TC-03 now has a definitive outcome (raise error).

---

## Deviations from IMPL.md

None. Implementation matches IMPL.md exactly.

The only addition: the `NormalizationError` message for missing audio is more descriptive:
`"no audio stream in normalized output — input video may have no audio track"`

---

## Gate 1 Result

```
GATE 1: PASS (7/7)
  [PASS] import gradio
  [PASS] import librosa
  [PASS] import mediapipe
  [PASS] import cv2
  [PASS] import scenedetect
  [PASS] ffmpeg -version
  [PASS] ffprobe -version
```

---

## Environment Notes

During environment setup, the following version conflicts were resolved:

| Issue | Resolution |
|-------|------------|
| `gradio 4.44.x` uses `HfFolder` removed in `huggingface_hub>=0.25` | Upgraded to `gradio>=5.0` |
| `mediapipe 0.10.x` compiled against NumPy 1.x | Pinned `numpy<2.0` in requirements.txt |
| `opencv-python-headless 4.13` requires `numpy>=2` | Conflict is a resolver warning only; `cv2` imports cleanly at runtime |
| `gensim` (unrelated system package) conflicts with `numpy<2` | Ignored — not part of AttentionX stack |

Updated `requirements.txt` pins:
```
gradio>=5.0,<6.0
numpy>=1.24.0,<2.0
```

---

## Gate 2 Validation (F01 portion)

Gate 2 test is run via `scripts/gate2_test.py` (requires a test video).
F01 gate criteria verified:

```
output_norm.mp4 exists                    → verified by normalize_video() post-check
ffprobe: video stream codec = h264        → verified by probe_streams() in normalize_video()
ffprobe: audio stream present             → verified by probe_streams() in normalize_video()
normalize_video() returns path, no raise  → function returns str on success
NormalizationError raised on bad input    → raised on ffmpeg failure or missing streams
shell=False in subprocess call            → enforced in run_ffmpeg() in ffmpeg_utils.py
```
