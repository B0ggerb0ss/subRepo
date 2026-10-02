# AttentionX — Technology Stack (techstack.md)

> Format: each entry defines ROLE → WHY → HOW → CONSTRAINTS → VALIDATION.
> Agents must consult this file before selecting libraries or APIs for any pipeline stage.

---

## LAYER 1 — HOSTING & DEPLOYMENT

### Hugging Face Spaces

```
ROLE        Host the full public MVP as a single running Python process.
WHY         Free-tier CPU environment: 16 GB RAM, 2 CPU cores, 50 GB ephemeral disk.
            Purpose-built for ML demos. Public URL with zero ops overhead.
HOW         - Deploy repository root directly as a Space.
            - App entrypoint: app.py (Gradio-based).
            - Use ephemeral temp storage only (data/temp/, data/outputs/).
            - No persistent writes; files are cleared between sessions.
            - GPU upgrade available through Space settings if needed later.
CONSTRAINTS - No persistent database.
            - No user accounts.
            - Disk writes must stay within 50 GB ephemeral limit.
VALIDATION  - Public URL loads app UI.
            - Upload + generate flow completes end-to-end.
            - At least one output clip is downloadable by an external user.
```

---

## LAYER 2 — UI FRAMEWORK

### Gradio

```
ROLE        Browser-facing upload, pipeline trigger, preview, and download interface.
WHY         Wraps arbitrary Python functions into a web demo with very little code.
            Native support for video/file input and output components.
            Video component handles playable browser-format output (MP4/H.264).
HOW         - gr.Video          → long-form video upload
            - gr.File (multiple) → optional reference clips upload
            - gr.Button         → trigger pipeline
            - gr.Video / gr.Files → output preview and download
            - gr.Progress / gr.Textbox → optional status display
CONSTRAINTS - Do not build a separate React frontend.
            - Do not add a REST API layer.
            - Keep UI code in app.py only; no UI logic in services/.
VALIDATION  - `python app.py` starts without error.
            - UI renders in browser.
            - Upload one MP4, click submit, receive downloadable output.
```

---

## LAYER 3 — SPEECH TRANSCRIPTION

### faster-whisper

```
ROLE        Convert video speech into timestamped text segments.
WHY         CTranslate2-based Whisper reimplementation.
            Up to 4x faster than original Whisper, lower memory, same accuracy profile.
            Critical on CPU-bound free-tier hosting.
HOW         - Extract WAV from normalized MP4 (via ffmpeg).
            - Load model: "base" or "small" (trade accuracy for speed on CPU).
            - Run transcription → receive (start, end, text) segment list.
            - Optionally request word-level timestamps for caption precision.
            - Output: list of TranscriptSegment(start, end, text).
CONSTRAINTS - Use "base" by default; allow "small" as a config option.
            - Do not use "large" or "large-v3" on CPU-tier (memory risk).
            - Word-level alignment is optional; fall back to segment-level if slow.
VALIDATION  - Non-empty transcript returned for a 30–60s speech sample.
            - Timestamps are monotonically increasing.
            - At least 3 sampled phrases match audio on manual review.
```

---

## LAYER 4 — AUDIO FEATURE ANALYSIS

### librosa

```
ROLE        Compute frame-level audio energy to detect emotional peaks and emphasis.
WHY         librosa.feature.rms computes root-mean-square energy per frame.
            RMS is a lightweight, reliable proxy for vocal intensity.
            Easy to align with transcript segment timestamps.
HOW         - Load WAV as mono (librosa.load, sr=22050).
            - Compute RMS: librosa.feature.rms(y=audio).
            - Convert frame indices to seconds using librosa.frames_to_time.
            - Normalize RMS to [0, 1].
            - Identify windows above 75th-percentile threshold as "energy peaks".
            - Return: list of (start_sec, end_sec, rms_score).
CONSTRAINTS - Process mono audio only.
            - Keep hop_length default (512) unless tuning is needed.
            - Do not stream audio; load entire clip per segment candidate.
VALIDATION  - Non-empty RMS array returned.
            - Energy peaks overlap with audibly emphatic or loud moments.
            - Peak timestamps can be plotted and manually verified.
```

---

## LAYER 5 — FACE DETECTION & TRACKING

### MediaPipe (mediapipe)

```
ROLE        Detect speaker face location per sampled frame; derive crop-anchor coordinates.
WHY         MediaPipe Face Detector locates faces and keypoints in images/video.
            Face Landmarker supports landmarks and expressions in streams.
            Practical for speaker-centered crop logic on CPU.
HOW         - Sample video at N frames per second (default: 2 fps, configurable).
            - Run mp.solutions.face_detection on each sampled frame.
            - Extract bounding box center (cx, cy) for dominant face.
            - Interpolate center coordinates across frames for smooth crop window.
            - Compute face visibility ratio: frames_with_face / total_frames.
            - Compute face stability score: variance of (cx, cy) over time.
            - FALLBACK: if no face detected in a frame, use frame center (0.5, 0.5).
CONSTRAINTS - Never process every frame; use sampled frames only (CPU budget).
            - Always implement center-crop fallback when face confidence < threshold.
            - Face landmarker is optional (expressions as bonus signal only).
VALIDATION  - Bounding boxes or center coordinates returned for a talking-head clip.
            - Face-center moves smoothly (no large single-frame jumps).
            - Zero-face fallback activates without exception on a non-face clip.
```

---

## LAYER 6 — SCENE DETECTION

### PySceneDetect (scenedetect)

```
ROLE        Detect shot transitions; make clip boundaries visually coherent.
WHY         Purpose-built for shot-change detection in video.
            Returns scene timestamps usable for candidate window construction.
            Integrates with FFmpeg for video splitting if needed.
HOW         - Run ContentDetector on normalized MP4.
            - Extract scene list: list of (start_timecode, end_timecode).
            - Convert to seconds: list of float timestamps.
            - Use scene boundaries to:
              a) avoid candidate windows that start/end mid-cut
              b) penalize candidates that span too many scene boundaries
CONSTRAINTS - False positive rate must be acceptable (tune threshold if needed).
            - Do not split files using PySceneDetect's built-in splitter;
              use FFmpeg for all rendering.
VALIDATION  - Scene timestamps returned for a video with known visual cuts.
            - Detected count is reasonable (not hundreds of false positives).
            - Timestamps roughly align with visible cut points.
```

---

## LAYER 7 — MEDIA PROCESSING & RENDERING

### FFmpeg (via subprocess)

```
ROLE        All media I/O: normalization, audio extraction, trimming, cropping,
            caption burn-in, and final export.
WHY         Universal media converter with deterministic filter pipeline.
            Faster and more reliable than pure-Python media manipulation.
            Required for H.264 output compatible with Gradio video playback.
HOW         Operations (each as a discrete subprocess call):
            1. NORMALIZE:   ffmpeg -i input -c:v libx264 -c:a aac output_norm.mp4
            2. AUDIO:       ffmpeg -i norm.mp4 -vn -ar 22050 -ac 1 audio.wav
            3. TRIM:        ffmpeg -ss START -to END -i norm.mp4 -c copy segment.mp4
            4. CROP 9:16:   ffmpeg -i seg.mp4 -vf "crop=w:h:x:y" vertical.mp4
                            where w = source_height * 9/16, h = source_height,
                            x = face_center_x - w/2 (clamped to frame bounds)
            5. CAPTIONS:    ffmpeg -i vertical.mp4 -vf subtitles=clip.srt final.mp4
            6. VERIFY:      ffprobe -v error -select_streams v:0 final.mp4
CONSTRAINTS - All FFmpeg commands must be deterministic (no random seeds).
            - Validate each output with ffprobe before passing to next stage.
            - Never skip the normalization step; always process from norm.mp4.
            - Output must be H.264 MP4, browser-playable.
VALIDATION  - Output file plays in browser without transcoding.
            - Aspect ratio confirmed as 9:16.
            - Captions are visible and time-aligned.
            - ffprobe reports no codec errors.
```

---

## LAYER 8 — OPTIONAL LLM ENHANCEMENT

### Gemini API (google-generativeai)

```
ROLE        Generate hook headlines and clip summaries for UI display.
WHY         Free tier available for new Gemini Developer API accounts.
            Text-only usage (send transcript snippet, receive headline).
            Low latency addition that improves polish without risk to core pipeline.
HOW         - Gate behind: GEMINI_API_KEY environment variable.
            - Input: transcript text of selected clip (text only, never raw video).
            - Prompt: generate one hook headline (≤ 10 words) + one-sentence summary.
            - Return: (hook_text, summary_text) or ("", "") if key absent/call fails.
CONSTRAINTS - MUST be non-blocking: pipeline succeeds without Gemini.
            - NEVER send raw video bytes to Gemini.
            - NEVER make Gemini a required import (wrap in try/except).
            - Free tier only; no billing integration.
VALIDATION  - API key absent → pipeline completes, hook fields empty.
            - API key present → one headline + one summary returned per clip.
            - Disabling Gemini does not break any other pipeline stage.
```

---

## DEPENDENCY SUMMARY

```
# Core runtime
gradio>=4.0
faster-whisper>=1.0
librosa>=0.10
mediapipe>=0.10
scenedetect[opencv]>=0.6
opencv-python-headless>=4.8
numpy>=1.24
scipy>=1.11

# System (packages.txt for HF Spaces)
ffmpeg

# Optional
google-generativeai>=0.5
```

---

## WHAT IS EXPLICITLY NOT IN THE STACK

| Rejected Technology     | Reason                                              |
|-------------------------|-----------------------------------------------------|
| PyTorch / TensorFlow    | Too heavy for CPU-tier; not needed for this stack   |
| Celery / Redis          | No async job queue; single-process is correct here  |
| PostgreSQL / SQLite     | No persistent storage in scope                      |
| React / Next.js         | Gradio covers all UI needs for this MVP             |
| Whisper (original)      | faster-whisper is 4x faster with same accuracy      |
| OpenCV VideoWriter      | FFmpeg is more reliable for final render            |
| LangChain               | Unnecessary abstraction over a single Gemini call   |
| Docker                  | HF Spaces handles containerization natively         |
