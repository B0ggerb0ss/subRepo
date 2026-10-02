# ADR-011 — Video assets in the shared library (M8)

**Status:** accepted 2026-10-02 · **Code:** `services/analyze/videoio.py`, `services/analyze/video.py`,
`services/library/{ingest,metadata}.py`, `services/search/{lexical,vectors,service}.py`, `ui/{library,inspector}.py`,
`app.py` (`generate_from_library`) · **Tests:** `tests/integration/test_m8_video_library.py`, e2e `test_10`.

## Decision

A video is **one library asset** (`kind='video'`), stored immutably like an image. It is analyzed through
**sampled keyframes**, and every observation keeps a time anchor (`frame_id`, `t_s`).

1. **Admission** (`videoio.probe_video`): ffprobe checks for a video stream, a known duration, and size/duration
   limits (`LIBRARY_MAX_VIDEO_MB` 4096, `LIBRARY_MAX_VIDEO_MINUTES` 180). Failures get a sanitized code
   (`corrupt_video`, `no_video_stream`, `too_long`, ...) and the rest of the batch continues.
2. **Keyframes** (`videoio.sample_keyframes`, `keyframes/1.1`): one streaming FFmpeg decode at 1 fps, scaled to
   ≤1280 px with rotation applied. A frame is kept when it is the first frame, when the content changes (≥1 % of
   pixels change by >25 on a 64×36 gray view), or when the max gap (10 s) has passed since the last kept frame.

   The keyframe budget (`LIBRARY_VIDEO_MAX_KEYFRAMES`, default 120) is **spread over the whole video**:
   consecutive keyframes are at least `min_gap = max(1/fps, duration/(cap−1))` apart. Busy footage is
   therefore sampled sparsely but completely, and the effective `min_gap_s`/`max_gap_s` are recorded.

   Why: the first version spent the budget at the start and truncated a 300 s busy video at 120 s (recall
   21/60). With the budget spread, coverage is complete and recall is 56/60 (`reports/benchmark.md`). If the cap
   is still hit (it is kept as a guard), coverage is reported incomplete with a reason and the asset is `partial`.

   Only the last kept frame's signature is held in memory. Keyframes are written as JPEG under
   `derived/keyframes/<hash>_<stage-key>/`; the directory is keyed by the stage cache key, so a policy change
   never reuses stale frames.
3. **Per-keyframe analysis** reuses the image providers, with no new models:
   - RapidOCR runs per frame; OCR region polygons are normalized to that frame.
   - CLIP runs on the letterboxed global view (same preprocessing, so the **same namespace** as images and
     directly comparable).
   - MiniLM chunks are built per frame, so a chunk never mixes frames.
   - The detector runs per frame.

   Stage names match the image plan, so commit, indexing and the cache contract are shared. Their versions
   differ, and their keys include the video's content hash.
4. **Literal search across frames.** The OCR document puts a non-word separator line (`␞`) between keyframes.
   A literal phrase therefore can never match text split across two frames (tested).
5. **Speech.** The `transcript` stage runs only when ASR is enabled *and* Whisper weights are provisioned
   locally. Otherwise it is `disabled` or `missing` with a reason; there is no download and no cloud. Typed
   context/scene questions are image questions, so `context` is `not_applicable` for videos.
6. **Metadata.** Video documents are `MediaMetadata/1.2`, which adds:
   - a `video` record (probe facts, keyframes with spans, policy, coverage);
   - an optional `speech` record;
   - `frame_id`/`t_s` on OCR regions, detections and embedding views.

   Image documents stay 1.1. The model rejects frame anchors or video/speech records in a 1.1 document. The
   1.0 projection maps keyframe spans to timed `text_layers` and speech to `asr` layers.
7. **Search.** Evidence carries `frame_id`/`t_s`:
   - The inspector shows the keyframe of the first evidence item and draws only that frame's geometry.
   - Gallery captions show `▶ duration` and `@ m:ss`.
   - Word evidence on videos is restricted to the single best frame.
   - `type:video|image` and `format:mp4|webm` filters are available.
   - "Find similar" works from a chosen keyframe, or from a crop of it.
8. **Organization.**
   - Videos join a deterministic **Videos** smart set and are kept out of "Needs review".
   - Similarity groups use `global` image views only, so videos are not grouped (yet).
   - Near-duplicates of videos are only exact-byte reuse; perceptual hashes are image-only.
9. **Generate reuse** (`app.generate_from_library`).
   - The Generate tab lists library videos. It reads the managed original (never modified) and caches the
     normalized H.264/AAC proxy at `derived/normalized/<hash>_<recipe>.mp4`, keyed by content hash plus the
     normalization recipe (`services.ingest.NORMALIZE_VERSION`).
   - When the library has a transcript for those bytes, ASR is not run again.
   - The five-value `run_pipeline` output contract is unchanged.

## Why not frames as separate image assets

Frames as separate assets would reuse more code with no changes. But they would:
- pollute the gallery, collections, duplicates and similarity groups with hundreds of near-identical images;
- need a parent link at every one of those touch points;
- break content-addressed identity (identical frames in two videos would collapse into one asset).

## Limits (documented, not hidden)

- Text shown for less than the effective keyframe spacing can be missed: 1 s at minimum, and duration/119 for
  long videos (≈90 s for a 3 h video at the default budget; raise `LIBRARY_VIDEO_MAX_KEYFRAMES` for denser
  sampling).
- Gradual changes are only sampled at the max-gap rate.
- OCR dominates the cost (≈0.9 s per 720p keyframe on 4 CPUs).
- Speech search is **not built**: no ASR weights could be provisioned here, so it could not be verified.
- Similarity groups and perceptual near-duplicates are not computed for videos.
- Trimming in Generate re-encodes from the cached normalized proxy. A clip render is a new encode by design (exact
  ranges, ADR-007).
