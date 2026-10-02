# Performance report — 2026-09-30

Machine: 4 logical CPUs (Intel Xeon @ 2.10 GHz, container), 16 GB RAM, SSD-backed overlay, **no GPU**.
This is *below* the prompt's reference profile (8 logical cores). Python 3.11.15, ONNX Runtime 1.30.0
(CPU EP), SQLite 3.45.1 WAL. Raw data: `reports/benchmark.json` (`scripts/benchmark_image_library.py`).

## Targets

| Budget | Target | Measured | Status |
|---|---|---|---|
| UI job submission (copy + hash + register + enqueue, 800×600 PNG) | p95 < 200 ms | **p95 5.3 ms** (p50 2.0) | met |
| Warm lexical / filter search, ~9.8k assets | p95 < 200 ms | **p95 119 ms** (p50 62) | met |
| Warm hybrid search incl. query encoding, ~9.8k assets | p95 < 1 s | **p95 240 ms** (p50 190) | met |
| Committed metadata reopen | p95 < 50 ms | **p95 0.98 ms** | met |
| ~2 MP image, pixels + OCR (basic profile) | p95 < 3 s | **p95 2.43 s** (p50 1.55; 1920×1080, 5 text-heavy + 5 photos) | met |
| ~2 MP full analysis (+ CLIP views, MiniLM, detector, context, index, organize) | report | p50 2.43 s, p95 3.92 s | reported |
| No whole-library re-inference after one import / edit / correction | — | verified by tests (stage cache, context-only re-runs); one new image into ~9.8k: analyze + organize 7.4 s, of which incremental organize **0.12 s** vs full organization rebuild 12.3 s | met |
| Model/index migration keeps old snapshot searchable | — | shadow namespace + atomic promotion on full coverage (tested); **partial**: the old snapshot stays in the DB but querying it needs the old encoder, which is not kept provisioned — the visual channel reports "degraded" until promotion | partial |

## Analysis profile (30 real eval images, warm worker in one process)

| | p50 | p95 |
|---|---|---|
| per image, all stages | 0.63 s | 2.22 s |
| pixels + OCR | 0.40 s | 1.78 s |
| OCR stage (1.5× scale, tiling) | 0.31 s | 1.61 s |
| CLIP image views (global + ≤4 regions) | 0.16 s | 0.19 s |
| EfficientDet-Lite0 | 0.04 s | 0.06 s |

Cold model loads: RapidOCR 0.29 s, CLIP text 0.75 s, CLIP visual 0.73 s, MiniLM 0.18 s, detector 0.48 s.
Throughput on the whole eval set (378 assets, 2 worker processes × 2 ORT threads): 476 s wall
from scratch (≈ 0.8 images/s); re-analysis after an OCR/context version change: pixels, CLIP views and
objects all served from cache.

Memory (VmHWM) of one warm analysis process with all providers: **≈ 1.8 GB**; a search process
holding the ~9.8k-asset vector matrices plus encoders: **≈ 2.9 GB**. These are below the 16 GB budget
but far above model file sizes — bound concurrency by worker count, not weight size.

## Index size at ~9.8k assets (synthetic scale rows)

The 10k search benchmark replicates the 378 analyzed eval assets ×26 with new ids and perturbed
vectors (clearly *not* new analyses): 9,828 assets, 119,340 vectors (CLIP views, OCR chunks and body
vectors), **773 MB** SQLite file — dominated by metadata revision payloads and vectors. First query
after start (encoders + matrix load): 2.1 s. Exact cosine over the matrices is still well inside the
latency budget, so no ANN backend was introduced (ADR-004).

## Fixes driven by these measurements

- Search cache key: full-table `MAX()` scans (78 ms/query at 10k) → O(1) write-sequence counter.
- Evidence (pydantic objects, region lookups) built for every candidate → only for the returned page.
- Filter evidence parsed metadata JSON per asset → `prob_kind` columns (schema v4).
- Per-asset duplicate check parsed every asset's metadata (3.0 s at 10k) → hash columns (schema v5): 0.04 s.

## Video in the library (M8) — 2026-10-02

Raw data: `reports/benchmark_video.json` (`scripts/benchmark_video_library.py`). Same 4-CPU container, warm providers.
Inputs are FFmpeg-rendered 1280×720 `testsrc2` (a full-frame moving pattern, the worst case for change detection)
with a new boxed text line every 5 s and a sine audio track. They show cost and plumbing, **not** real-footage
OCR quality.

| | 60 s video (18 MB) | 300 s video (91 MB) |
|---|---|---|
| admission (ffprobe + copy + hash + enqueue) | 125 ms | 265 ms |
| keyframes (one streaming 1 fps decode) | 60 · 1.8 s | 100 · 7.8 s |
| OCR over keyframes | 54.6 s | 91.8 s |
| CLIP / MiniLM / detector | 4.9 / 2.5 / 2.8 s | 5.7 / 3.6 / 3.6 s |
| total analysis | 66.8 s (1.11× realtime) | 112.5 s (0.38× realtime) |
| keyframe disk (JPEG q92, ≤1280 px) | 5.4 MB | 8.9 MB |
| timed literal recall of rendered lines | 9/12 | 56/60 |
| max timestamp error of found lines | 1.0 s | 4.0 s |
| `text:"…"` search p50 / p95 | 1.0 / 1.2 ms | 1.5 / 2.4 ms |

- **Driven by this measurement.** The first policy (change detection plus a fixed 120-keyframe cap) spent the
  whole budget in the first 120 s of the 300 s video. Coverage was then reported incomplete, and recall was
  21/60. The keyframe budget is now spread over the whole duration (`min_gap = duration / (cap − 1)`, here
  3 s; `keyframes/1.1`). Coverage became complete and recall went to 56/60. The trade-off is documented: text
  visible for less than the effective spacing can be missed, and the spacing is recorded in the metadata
  (`video.min_gap_s`).
- Misses are OCR errors on the busy background (`0`→`o`, `1`→`l`, dropped trailing digits), not
  indexing.
- OCR is about 80 % of video analysis cost (≈0.9 s per 720p keyframe). Static footage (talks, screen
  recordings) produces far fewer keyframes, because only content changes and the 10 s max gap add one.
- **Generate from a library video** (60 s source): the first run took 19.8 s including normalization. The
  second took 7.7 s, reusing the cached normalized proxy (`derived/normalized/`).
