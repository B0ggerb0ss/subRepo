# Feature status

Legend: **verified** = implemented and backed by the cited passing test/measurement ·
**verified (stand-in)** = gate measured only on the synthetic-rendered + real-photo stand-in set ·
**implemented_unverified** = code exists, the acceptance evidence is missing · **blocked** = cannot be
completed in this environment (reason given) · **not_started**.

Test suite on 2026-09-30: `bash run_tests.sh all` → 71 passed (unit + integration, real FFmpeg,
RapidOCR, ONNX CLIP/MiniLM, EfficientDet, SQLite); `bash run_tests.sh e2e` → 9 passed (real Chromium
against the running app). Evaluation: `reports/evaluation.md`; performance: `reports/benchmark.md`.

## Gates

| Gate | Status | Evidence / remaining |
|---|---|---|
| M0 verified baseline | **verified** | `docs/current-state.md`; original suite 26 passed; audit defects reproduced as regression tests (`tests/unit/test_legacy_regressions.py`) |
| M1 durable import | **verified** | `test_m2_ocr_search_slice.py`: JPEG/PNG/WebP import, restart, identical-bytes reuse with separate import records, corrupt/unsupported isolation; e2e batch + folder import |
| M2 first usable slice | **verified** | meaningless filename found by `text:"feature store"`, polygon checked against rendered box; restart without re-OCR; annotation edit reruns nothing; missing OCR weights → `missing` then recovered by retry; e2e verifies the highlight pixels in the browser |
| M3 contextual retrieval | **verified (stand-in)** | description, OCR-meaning (verbatim evidence), namespace refusal, grammar errors tests; visual nDCG 0.86, OCR-meaning recall **0.74 (< 0.80)** |
| M4 objects/scenes/source | **partly verified; object/scene accuracy blocked** | real boxes + raw detector scores; LinkedIn UI vs brand mention vs prompt injection; black bars ≠ film; photos → source `not_applicable`. Object/scene precision/recall **NOT TESTED** (COCO/Places unreachable; no scene positives) |
| M5 organization | **implemented; below target** | LinkedIn P 1.00/R 0.90, movie P 1.00/R 0.73 (synthetic); duplicates strict P 0.89 (adjudicated 1.00)/R 1.00, 0 chrome/crop false pairs; similarity-group F1 0.35–0.63 **< 0.80** |
| M6 corrections | **verified** | rename/pin/exclude/move/merge/split/create/set_decision; survives re-analysis, reclustering, restart; late job `superseded`; stale revision rejected (M6 tests + e2e restart flow) |
| M7 usable UI | **verified** | 9 real-browser flows: batch import + analysis progress, text search with highlight, object/source filters + query errors, crop similarity, annotations, retry/cancel + stage table, pagination (51 images), collection rename/exclude/export, restart |
| M8 legacy/shared media | **partly verified** | Generate contract kept; exact range, crop/pad, captions, silent video, ASR-missing degradation verified with FFmpeg. **not_started:** video assets in the library, shared video metadata, trim reuse of source analysis |
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
| Reference & crop similarity | verified (stand-in); crop below target | crop nDCG 0.62 |
| Typed decisions (23 heads, calibrated where dev data allows) | verified (stand-in) for capture/source/context; topics weak; scenes untested | ADR-005 |
| OneJev decision backend | blocked | GitHub/HF unreachable; CLIP zero-shot backend used instead |
| Smart collections + needs-review | verified (stand-in) | thresholds selected on dev |
| Similarity groups (stable ids, aliases, pins) | implemented; quality below target | F1 0.35–0.63 |
| Near-duplicate candidates, collapse in search | verified (stand-in) | never deletes |
| Export snapshot (1.1 / 1.0 projection), deterministic | verified | identical sha256 on repeat; 1.0 validates |
| Vector namespace migration | partial | shadow build + atomic promotion tested; old snapshot not queryable without its encoder |
| ASR in Generate | blocked | Whisper weights unprovisionable here; no implicit download; visible degradation |
| Style replication / Gemini hooks | not_started (legacy stubs) | labelled in UI; not extended |
| Hosted multi-user profile (auth, ownership) | not_started | loopback-only by default |

## Remaining work (next gates)

1. Collect/licence the 500-image pilot with two raters; re-fit calibration and thresholds on it.
2. Provision an object/scene evaluation set (COCO val / Places subsets) or a local mirror; measure precision/recall.
3. Provision OneJev (or another evaluated local vision decision model) behind the `context` stage.
4. Improve English OCR word segmentation (e.g. PP-OCRv5 English recognizer) — the main literal-recall limiter.
5. Similarity groups: learn per-scope thresholds on real data; consider HDBSCAN once measured.
6. Video assets in the library and shared metadata for Generate (M8).
