# AttentionX — Roadmap (roadmap.md)

> Phases map to delivery milestones. Each milestone maps to one or more Features.
> Each Feature has its own folder in Features/ with SPEC.md, IMPL.md, VALIDATION.md.
> Gates are the pass/fail checkpoints. A gate must pass before the next phase begins.

---

## OVERVIEW

```
Phase 1  →  Project foundation & environment
Phase 2  →  Ingestion pipeline (upload, normalize, extract)
Phase 3  →  Intelligence pipeline (transcribe, audio, face, scene)
Phase 4  →  Ranking engine (segment build, scoring)
Phase 5  →  Rendering pipeline (captions, crop, export)
Phase 6  →  UI integration (Gradio, end-to-end flow)
Phase 7  →  Optional enhancements (Gemini, style replication)
Phase 8  →  Public deployment (Hugging Face Spaces)
```

---

## PHASE 1 — PROJECT FOUNDATION

**Goal:** repository structure, environment, and baseline import verification.

### Milestone 1.1 — Directory scaffolding

- Create `app.py`, `requirements.txt`, `packages.txt`
- Create `services/`, `models/`, `utils/`, `data/temp/`, `data/outputs/`
- Create `SPECs/`, `Features/` documentation structure

**Feature files:** none (infrastructure only)

### Milestone 1.2 — Dependency installation

- Install Python deps from `requirements.txt`
- Verify FFmpeg available via `ffmpeg -version`
- Run import smoke test

**Gate 1 — Environment**

```
PASS CRITERIA:
  import gradio, librosa, mediapipe, cv2, scenedetect  → no ImportError
  subprocess.run(["ffmpeg", "-version"])                → returncode 0
  subprocess.run(["ffprobe", "-version"])               → returncode 0
FAIL ACTION:
  Fix missing package or system dependency before proceeding.
```

---

## PHASE 2 — INGESTION PIPELINE

**Goal:** accept uploaded video, normalize format, extract audio track.

### Milestone 2.1 — Input normalization

- Accept uploaded MP4 (or any format)
- Transcode to H.264 MP4 (`output_norm.mp4`) with known codec and container
- Verify output plays and has video + audio streams

**Feature:** [Features/F01-input-normalization/](../Features/F01-input-normalization/)

### Milestone 2.2 — Audio extraction

- Extract mono WAV from normalized MP4 at 22050 Hz
- Verify WAV file exists and has correct sample rate

**Feature:** [Features/F02-audio-extraction/](../Features/F02-audio-extraction/)

**Gate 2 — Video Ingestion**

```
PASS CRITERIA:
  output_norm.mp4 exists and plays
  ffprobe confirms video stream: codec=h264
  ffprobe confirms audio stream present
  audio.wav exists, sr=22050, mono
FAIL ACTION:
  Re-run normalization with explicit codec flags. Log ffmpeg stderr.
```

---

## PHASE 3 — INTELLIGENCE PIPELINE

**Goal:** run all four analysis passes to produce signals for scoring.

### Milestone 3.1 — Speech transcription

- Run faster-whisper on extracted WAV
- Return list of `TranscriptSegment(start, end, text)`
- Timestamps monotonically increasing

**Feature:** [Features/F03-transcription/](../Features/F03-transcription/)

**Gate 3 — Transcription**

```
PASS CRITERIA:
  Non-empty segment list returned
  start < end for every segment
  timestamps monotonically increasing
  3+ sampled phrases manually verified against audio
FAIL ACTION:
  Try smaller model. Check audio is valid WAV. Inspect segment count.
```

### Milestone 3.2 — Audio energy analysis

- Compute RMS curve from WAV
- Identify energy-peak windows above 75th-percentile threshold
- Return list of `EnergyPeak(start, end, rms_score)`

**Feature:** [Features/F04-audio-energy/](../Features/F04-audio-energy/)

**Gate 4 — Audio Analysis**

```
PASS CRITERIA:
  Non-empty RMS array with time axis
  At least one energy peak identified
  Peak timestamps overlap audibly emphatic moments (manual check)
FAIL ACTION:
  Adjust percentile threshold. Verify WAV loaded as mono.
```

### Milestone 3.3 — Face detection and tracking

- Sample frames at 2 fps from normalized MP4
- Run MediaPipe face detection per sampled frame
- Return `FaceTrack(frame_times, centers, visibility_ratio, stability_score)`
- Center-crop fallback when no face detected

**Feature:** [Features/F05-face-tracking/](../Features/F05-face-tracking/)

**Gate 5 — Face Analysis**

```
PASS CRITERIA:
  Face centers returned for talking-head clip
  Centers change smoothly (no single-frame discontinuities > 0.2 normalized)
  visibility_ratio > 0.5 for a clearly visible speaker clip
  Fallback activates without exception on a no-face clip
FAIL ACTION:
  Reduce confidence threshold. Check sampling fps. Verify fallback path.
```

### Milestone 3.4 — Scene detection

- Run PySceneDetect ContentDetector on normalized MP4
- Return list of scene-boundary timestamps in seconds
- Acceptable false-positive rate (< 1 false cut per 10 seconds on stable footage)

**Feature:** [Features/F06-scene-detection/](../Features/F06-scene-detection/)

**Gate 6 — Scene Detection**

```
PASS CRITERIA:
  Non-empty scene list for a video with known visual cuts
  Detected timestamps roughly align with visible cut points
  False positive count acceptable (< 1 per 10s on stable talking-head)
FAIL ACTION:
  Tune ContentDetector threshold. Try AdaptiveDetector as alternative.
```

---

## PHASE 4 — RANKING ENGINE

**Goal:** fuse all signals into ranked candidate segments.

### Milestone 4.1 — Candidate segment construction

- Combine transcript windows (5–20 second chunks) with audio peaks and scene boundaries
- Avoid windows that start or end mid-cut
- Penalize windows spanning too many scene boundaries
- Return list of `CandidateSegment(start, end, transcript_text, signals)`

**Feature:** [Features/F07-segment-builder/](../Features/F07-segment-builder/)

### Milestone 4.2 — Multisignal highlight scoring

- Score each candidate with weighted formula:
  - transcript hook quality: 0.30
  - RMS energy score: 0.25
  - face visibility ratio: 0.25
  - scene coherence: 0.10
  - reference style match (optional): 0.10
- Return top N candidates (default: 3) sorted by score descending
- Include per-feature score breakdown for explainability

**Feature:** [Features/F08-highlight-scorer/](../Features/F08-highlight-scorer/)

**Gate 7 — Ranking**

```
PASS CRITERIA:
  Ranked list returned with at least 1 candidate
  Per-feature scores present for each candidate
  Top segment appears reasonable on manual review of the source video
  Scores sum to a normalized value (validate weighting math)
FAIL ACTION:
  Print all candidate scores. Inspect which signal is dominating.
  Adjust weights in models/settings.py.
```

---

## PHASE 5 — RENDERING PIPELINE

**Goal:** convert ranked segments into browser-playable 9:16 vertical clips with captions.

### Milestone 5.1 — Caption generation

- Generate SRT from transcript segments within each candidate window
- Line length ≤ 42 characters
- No overlapping subtitle blocks
- Write `clip_N.srt` to `data/temp/`

**Feature:** [Features/F09-caption-generation/](../Features/F09-caption-generation/)

**Gate 8 — Captions**

```
PASS CRITERIA:
  Valid SRT file produced with correct timestamp format
  No overlapping time ranges
  Line lengths ≤ 42 chars
  Manual review: subtitle text matches spoken audio
FAIL ACTION:
  Inspect segment boundaries. Check for off-by-one in timestamp conversion.
```

### Milestone 5.2 — Vertical crop and render

- Trim candidate window from normalized MP4
- Apply 9:16 crop filter centered on face-track anchor (or center fallback)
- Burn SRT captions into video
- Export H.264 MP4
- Verify with ffprobe

**Feature:** [Features/F10-vertical-render/](../Features/F10-vertical-render/)

**Gate 9 — Rendering**

```
PASS CRITERIA:
  Output MP4 plays in browser
  ffprobe confirms h264 video, aac audio
  Aspect ratio is 9:16 (width * 16 == height * 9)
  Captions visible and time-aligned
  Speaker remains in frame for majority of clip
FAIL ACTION:
  Test FFmpeg crop command in isolation. Check face center coordinates.
  Verify SRT format with a standalone player.
```

---

## PHASE 6 — UI INTEGRATION

**Goal:** wire all pipeline stages into the Gradio interface for end-to-end use.

### Milestone 6.1 — Gradio app assembly

- `app.py` wires upload → pipeline → output
- Progress status displayed during processing
- Output clips shown as playable video + downloadable files
- Input validation: file type, file size limit

**Feature:** [Features/F11-gradio-ui/](../Features/F11-gradio-ui/)

**Gate 10 (partial) — End-to-End Local**

```
PASS CRITERIA:
  python app.py starts without error
  UI renders in browser at localhost
  Upload one MP4, click Generate, receive at least one output clip
  Output plays and is downloadable
FAIL ACTION:
  Isolate which pipeline stage is failing. Run stages in isolation first.
```

### Milestone 6.2 — Reference style upload (optional input)

- Accept multiple reference short clips via `gr.File`
- Compute lightweight style profile (avg duration, face ratio, caption density)
- Bias scoring weight for reference-style-match signal

**Feature:** [Features/F12-style-replication/](../Features/F12-style-replication/)

---

## PHASE 7 — OPTIONAL ENHANCEMENTS

**Goal:** add non-critical polish features that are gated and safe to disable.

### Milestone 7.1 — Gemini hook generation

- Gate on `GEMINI_API_KEY` environment variable
- Generate ≤ 10-word hook headline per clip
- Generate one-sentence "why this clip was selected" summary
- Display in UI alongside output clip

**Feature:** [Features/F13-gemini-hooks/](../Features/F13-gemini-hooks/)

**Gemini gate:**

```
PASS CRITERIA (with key):   Hook text and summary returned for each clip
PASS CRITERIA (without key): Pipeline completes, hook fields display empty string
FAIL ACTION:
  Confirm key is loaded from env. Wrap call in try/except with fallback.
  Never let Gemini failure propagate to main pipeline.
```

---

## PHASE 8 — PUBLIC DEPLOYMENT

**Goal:** deploy to Hugging Face Spaces; produce a publicly accessible hosted MVP.

### Milestone 8.1 — Spaces configuration

- Create `packages.txt` with `ffmpeg`
- Verify `requirements.txt` is complete
- Push repository to Hugging Face Space
- Confirm build succeeds

**Feature:** [Features/F14-hf-deployment/](../Features/F14-hf-deployment/)

**Gate 10 (full) — Hosting**

```
PASS CRITERIA:
  Public Space URL loads Gradio UI
  Upload and generate flow completes on hosted environment
  At least one output clip is downloadable by external user
  No build failure in Space logs
FAIL ACTION:
  Check Space build logs. Verify packages.txt has ffmpeg.
  Check RAM usage during processing (stay within 14 GB working set).
```

---

## FEATURE REGISTRY

| ID  | Feature                  | Phase | Gate |
|-----|--------------------------|-------|------|
| F01 | Input Normalization      | 2     | 2    |
| F02 | Audio Extraction         | 2     | 2    |
| F03 | Transcription            | 3     | 3    |
| F04 | Audio Energy Analysis    | 3     | 4    |
| F05 | Face Tracking            | 3     | 5    |
| F06 | Scene Detection          | 3     | 6    |
| F07 | Segment Builder          | 4     | 7    |
| F08 | Highlight Scorer         | 4     | 7    |
| F09 | Caption Generation       | 5     | 8    |
| F10 | Vertical Render          | 5     | 9    |
| F11 | Gradio UI                | 6     | 10   |
| F12 | Style Replication        | 6     | 7*   |
| F13 | Gemini Hooks             | 7     | —    |
| F14 | HF Deployment            | 8     | 10   |

*F12 extends the scoring gate but is optional.

---

## DEPENDENCY GRAPH

```
F01 ──► F02 ──► F03 ──┐
                       ├──► F07 ──► F08 ──► F09 ──► F10 ──► F11 ──► F14
F02 ──► F04 ──────────┤
                       │
F01 ──► F05 ──────────┤
                       │
F01 ──► F06 ──────────┘

F12 ──► F08 (optional signal weight)
F13 ──► F11 (optional UI display)
```

Nothing in F13 or F12 should block F10 or F11 from delivering.
