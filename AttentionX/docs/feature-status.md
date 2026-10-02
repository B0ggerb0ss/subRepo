# Feature status

Legend: **verified** = implemented and backed by the cited passing test/measurement ·
**verified (stand-in)** = gate measured only on the synthetic-rendered + real-photo stand-in set ·
**implemented_unverified** = code exists, the acceptance evidence is missing · **blocked** = cannot be
completed in this environment (reason given) · **not_started**.

Test suite on 2026-10-02: `bash run_tests.sh all` → **81 passed** (unit + integration, real FFmpeg,
RapidOCR, ONNX CLIP/MiniLM, EfficientDet, SQLite; includes 10 M8 video-library tests);
`bash run_tests.sh e2e` → **10 browser flows** (real Chromium against the running app; see the e2e note in
the M7 row). Evaluation: `reports/evaluation.md`; performance: `reports/benchmark.md`.

## Gates

| Gate | Status | Evidence / remaining |
|---|---|---|
| M0 verified baseline | **verified** | `docs/current-state.md`; original suite 26 passed; audit defects reproduced as regression tests (`tests/unit/test_legacy_regressions.py`) |
| M1 durable import | **verified** | `test_m2_ocr_search_slice.py`: JPEG/PNG/WebP import, restart, identical-bytes reuse with separate import records, corrupt/unsupported isolation; e2e batch + folder import |
| M2 first usable slice | **verified** | meaningless filename found by `text:"feature store"`, polygon checked against rendered box; restart without re-OCR; annotation edit reruns nothing; missing OCR weights → `missing` then recovered by retry; e2e verifies the highlight pixels in the browser |
| M3 contextual retrieval | **verified (stand-in); OCR-meaning recall below target, blocked on a better text encoder** | description, OCR-meaning (verbatim evidence), namespace refusal, grammar errors tests; visual nDCG 0.86, OCR-meaning recall **0.74 (< 0.80)**. 2026-10-02 dev-tuned cut-off experiment improved dev but regressed combined queries on test → rejected (`reports/experiments_m3_ocr_semantic_tail.md`); remaining misses have cosine 0.13–0.31 under MiniLM-L6, a stronger local encoder cannot be provisioned here (HF 403) |
| M4 objects/scenes/source | **partly verified; object/scene accuracy blocked** | real boxes + raw detector scores; LinkedIn UI vs brand mention vs prompt injection; black bars ≠ film; photos → source `not_applicable`. Object/scene precision/recall **NOT TESTED** (COCO/Places unreachable; no scene positives) |
| M5 organization | **implemented; below target** | LinkedIn P 1.00/R 0.90, movie P 1.00/R 0.73 (synthetic); duplicates strict P 0.89 (adjudicated 1.00)/R 1.00, 0 chrome/crop false pairs; similarity-group F1 0.35–0.63 **< 0.80** |
| M6 corrections | **verified** | rename/pin/exclude/move/merge/split/create/set_decision; survives re-analysis, reclustering, restart; late job `superseded`; stale revision rejected (M6 tests + e2e restart flow) |
| M7 usable UI | **verified** | 10 real-browser flows: batch import + analysis progress, text search with highlight, object/source filters + query errors, crop similarity, annotations, retry/cancel + stage table, pagination (51 images), collection rename/exclude/export, restart, **video import → timed text search → keyframe highlight → Generate from library**. 2026-10-02: found and fixed a real race where a late collection-view refresh overwrote the "Rename to" box the user was typing in (rename then applied the old name); the box is no longer written by refreshes. Last 3 consecutive e2e runs: 10/10 each |
| M8 legacy/shared media | **verified (synthetic video); speech search blocked** | Generate contract kept; exact range, crop/pad, captions, silent video, ASR-missing degradation verified with FFmpeg. **Video assets in the library** (ADR-011): ffprobe admission, bounded keyframe sampling, per-keyframe OCR/CLIP/MiniLM/detector with `frame_id`/`t_s`, MediaMetadata/1.2, timed literal search + keyframe highlight, no cross-frame phrase matches, `type:`/`format:` filters, similar-from-keyframe and crop, Videos smart set, cancel/retry with cache reuse, interrupted-job recovery, keyframe-cap partial coverage, Generate from a library video reusing the cached normalized proxy (and a library transcript when present) — `test_m8_video_library.py` (10) + e2e `test_10`. **blocked:** ASR transcript/speech search (no Whisper weights provisionable) |
| M9 release | **not met** | offline profile verified (no outbound connection during analysis/search); pilot data, object/scene evaluation, OneJev, Whisper weights missing; several accuracy targets below goal |

## Features

| Feature | Status | Notes |
|---|---|---|
| Admission limits (50 MB / 40 MP / decompression bomb), EXIF orientation | verified | `pixels.probe_image`, EXIF test |
| Animated images | verified | frame 0 analyzed; OCR coverage explicitly incomplete; later frames not claimed |
| HEIC, RAW, SVG, PDF, cloud sync, mobile | not_started | not advertised |
| Folder import without symlink traversal | verified | `ingest._walk_folder`; e2e folder import |
| Job queue: leases, cancel, retry, recovery | verified | M2/M6 tests, e2e retry/cancel |
| Hard cancel of a hung native call | implemented_unverified | `WorkerSupervisor.hard_restart` (process mode); no test forces a hang |
| RapidOCR tiling / overlap merge / reading order | verified (stand-in) | tall feeds (3 tiles) CER 0.20 driven by reading order |
| Tesseract explicit fallback | verified | provenance test |
| Non-Latin OCR (Arabic, Devanagari) | blocked | models not provisionable; reported as unsupported |
| Literal search incl. `C++`/`c#`/URLs, short strings, spacing-insensitive fallback | verified | tests + literal recall 0.906 (all misses OCR-side) |
| Typed grammar & AND filters | verified | parser errors, `source:linkedin text:"hiring"` |
| Hybrid RRF + evidence | verified (stand-in) | ablations in evaluation report |
| Reference & crop similarity | verified (stand-in); crop below target | crop nDCG 0.735 / R 0.667 on 80 test queries (was 5 queries). Cut-off and denser region views tested and ruled out; encoder-limited (`reports/experiments_m5_crop.md`) |
| Typed decisions (23 heads, calibrated where dev data allows) | verified (stand-in) for capture/source/context; topics weak; scenes untested | ADR-005 |
| OneJev decision backend | blocked | GitHub/HF unreachable; CLIP zero-shot backend used instead |
| Smart collections + needs-review | verified (stand-in) | thresholds selected on dev |
| Similarity groups (stable ids, aliases, pins) | implemented; quality below target | F1 0.35–0.63 |
| Near-duplicate candidates, collapse in search | verified (stand-in) | never deletes |
| Export snapshot (1.1 / 1.0 projection), deterministic | verified | identical sha256 on repeat; 1.0 validates |
| Vector namespace migration | partial | shadow build + atomic promotion tested; old snapshot not queryable without its encoder |
| ASR in Generate | blocked | Whisper weights unprovisionable here; no implicit download; visible degradation |
| Video import (MP4/MOV/M4V/WebM/MKV), keyframes, timed OCR search, inspector keyframe highlight | verified (synthetic) | `test_m8_video_library.py`, e2e `test_10`; real-footage OCR quality **NOT TESTED** |
| Video transcript stage / speech search | blocked (stage), not_started (search) | stage reports `disabled`/`missing`; reuse in Generate tested with a supplied transcript only |
| Video similarity groups / perceptual near-duplicates | not_started | videos excluded from both (documented in ADR-011) |
| Generate from a library video (cached normalized proxy) | verified | second run skips normalization; original bytes unchanged |
| Style replication / Gemini hooks | not_started (legacy stubs) | labelled in UI; not extended |
| Hosted multi-user profile (auth, ownership) | not_started | loopback-only by default |

## Remaining work (next gates)

1. Collect/licence the 500-image pilot with two raters; re-fit calibration and thresholds on it.
2. Provision an object/scene evaluation set (COCO val / Places subsets) or a local mirror; measure precision/recall.
3. Provision OneJev (or another evaluated local vision decision model) behind the `context` stage.
4. Improve English OCR word segmentation (e.g. PP-OCRv5 English recognizer) — the main literal-recall limiter.
5. Similarity groups: learn per-scope thresholds on real data; consider HDBSCAN once measured.
6. Provision Whisper weights to verify the video `transcript` stage and build speech search (M8 remainder).
7. Evaluate video keyframe OCR on real, licensed footage (only synthetic drawtext videos measured).
