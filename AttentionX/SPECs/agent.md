# AttentionX — Project Constitution (agent.md)

## MISSION

AttentionX is a single-deployment AI content repurposing engine.

It accepts one long-form horizontal video and produces one to three short-form vertical clips,
ready for direct posting to short-form platforms, with no manual timeline editing required.

The core promise: a creator uploads a video, clicks one button, and downloads platform-ready clips.

---

## NORTH STAR METRIC

> A first-time user goes from long-form upload to at least one usable 9:16 short-form clip
> without touching any manual editing timeline.

Everything built in this project must serve or protect that outcome.

---

## PRODUCT IDENTITY

- **What it is:** a compact multimodal video-repurposing engine
- **What it is not:** a collaborative editing suite, a social scheduler, a fine-tuning platform,
  a timeline editor, or an enterprise video SaaS
- **Deployment target:** single process, Hugging Face Spaces (CPU-tier), publicly accessible

---

## SYSTEM ROLE FOR AGENTS

When an agent operates on this codebase, it should treat every decision through this lens:

```
Does this change serve the user flow:
  Upload → Analyze → Score → Render → Download ?

If yes → proceed.
If no  → defer to the human.
```

Agents must not introduce:
- persistent user storage
- user authentication flows
- billing integration
- social platform APIs
- collaborative features
- timeline editors
- fine-tuned custom model hosting

Agents should always:
- prefer editing existing files over creating new ones
- keep FFmpeg commands deterministic and testable in isolation
- keep the Gemini integration strictly optional (never on the critical path)
- add comments only when the WHY is non-obvious
- validate each pipeline stage independently before composing the full pipeline

---

## CORE PIPELINE (ordered)

```
[1] Input Normalization      →  ffmpeg: transcode to H.264 MP4, extract WAV
[2] Transcription            →  faster-whisper: timestamped segments
[3] Audio Feature Analysis   →  librosa: RMS energy curve, peak detection
[4] Face Tracking            →  mediapipe: bounding boxes, face-center coords
[5] Scene Detection          →  pyscenedetect: shot-change timestamps
[6] Candidate Segment Build  →  fuse transcript + audio + scene windows (5–20s)
[7] Highlight Scoring        →  weighted multisignal score per candidate
[8] Caption Generation       →  SRT from transcript timestamps
[9] Vertical Crop Rendering  →  ffmpeg: 9:16 crop anchored to face center
[10] Export                  →  MP4/H.264, browser-playable, downloadable
```

---

## SCORING SIGNALS (weighted, configurable)

| Signal                  | Source           | Weight (default) |
|-------------------------|------------------|------------------|
| Transcript hook quality | faster-whisper   | 0.30             |
| RMS audio energy peak   | librosa          | 0.25             |
| Face visibility ratio   | mediapipe        | 0.25             |
| Scene coherence         | pyscenedetect    | 0.10             |
| Reference style match   | optional clips   | 0.10             |

---

## SCOPE BOUNDARIES

### In scope
- long video upload (single file)
- optional reference short clips upload
- transcript generation with timestamps
- RMS energy analysis and peak detection
- face detection and crop-anchor tracking
- scene boundary detection
- candidate segment construction (5–20 second windows)
- multisignal highlight scoring and ranking
- SRT caption file generation
- 9:16 vertical clip rendering with caption burn-in
- Gradio browser preview and file download
- Hugging Face Spaces public deployment

### Out of scope (hard boundary — do not implement)
- user accounts or authentication
- persistent storage or databases **for the video clip pipeline** (the local image
  library below is the authorized exception — see ADR-010)
- billing or payment integration
- timeline or manual editing UI
- collaborative editing
- fine-tuned or self-hosted model training
- batch processing at scale
- social platform publishing APIs (TikTok, YouTube, Instagram)

---

## TECHNICAL CONSTRAINTS

- **Deployment:** single Python process, Hugging Face Spaces CPU-tier
- **RAM budget:** ≤ 14 GB working set (Spaces provides 16 GB)
- **Disk budget:** ephemeral, ≤ 50 GB, no persistent writes outside `data/temp` and `data/outputs`
- **Frame sampling:** never process every frame — sample at intervals to stay within CPU budget
- **Fallback crop:** always implement center-crop fallback when no face is detected
- **Gemini:** environment-variable-gated, pipeline must succeed without it
- **Output format:** MP4/H.264, browser-playable, verified with ffprobe before returning to UI

---

## VALIDATION GATE PROTOCOL

Each pipeline stage has an independent validation gate (see `roadmap.md` Gates 1–10).
An agent implementing a stage must verify its gate passes before marking the stage complete.

Gate pass criteria are defined per stage in `Features/` — each feature file contains
`SPEC.md`, `IMPL.md`, and `VALIDATION.md`.

---

## AGENT BEHAVIORAL DIRECTIVES

1. **One pipeline, one process.** Do not split into microservices.
2. **Fail loud, not silent.** Raise exceptions at stage boundaries; do not swallow errors.
3. **Deterministic renders.** FFmpeg commands must be reproducible given the same inputs.
4. **No speculative features.** Three similar lines is better than a premature abstraction.
5. **Gemini is always optional.** Gate it behind `GEMINI_API_KEY` env var; pipeline runs without it.
6. **Temp files are ephemeral.** Write to `data/temp/`, clean up on pipeline exit.
7. **Output files are final.** Write to `data/outputs/`, return paths to UI layer.
8. **Face fallback is mandatory.** Every crop path must handle zero-face detection.
9. **CPU-aware sampling.** Use frame sampling (not every frame) for face and scene analysis.
10. **Gate before composing.** Validate each stage output before feeding it to the next stage.

---

## IMAGE LIBRARY (authorized extension, 2026-09-30 — ADR-010)

The earlier prototype rules above conflicted with the requested persistent local
media library. They still govern the video clip path. For the image library:

- **Allowed:** a local SQLite library (`data/library/` by default) with immutable
  content-addressed originals, derived thumbnails/previews, stage cache, jobs,
  annotations, collections and exports under separate managed roots.
- **Process model:** the Gradio app plus one local analysis worker (spawned process,
  or thread). No microservices, no vector service, no queue infrastructure.
- **Network:** models are provisioned explicitly (`scripts/provision_models.py`,
  pinned in `docs/model-manifest.json`). Analysis and search never download and
  never fall back to a cloud service. `ANALYSIS_LOCAL_ONLY=1` is the default.
- **Binding:** loopback (`127.0.0.1`) by default. A hosted profile would need
  authentication and ownership filtering first — not implemented.
- **Never:** delete a user's source files, auto-delete duplicates, deploy or publish
  as part of development, or present uncalibrated scores as certainty.
- **Honesty:** every stage reports complete/cached/partial/missing/disabled/error
  distinctly; unavailable providers are shown, not faked. Feature status lives in
  `docs/feature-status.md` with evidence.
