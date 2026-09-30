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
