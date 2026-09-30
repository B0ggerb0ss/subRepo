# Evaluation protocol

## What the requested protocol needs (not available here)

A consented/licensed **500-image pilot** (≈200 screenshots, 150 natural images with supported
objects/scenes, 100 text-heavy captures, 50 hard negatives), two independent raters for ambiguous
context/relevance with recorded disagreements, splits by original post / scene / capture source,
and ≥ 60 judged queries. **This dataset was not supplied and could not be collected in this
session.** Every gate that depends on it is reported as *measured on a stand-in* or `NOT TESTED`,
never as passed.

## Stand-in set actually used (`scripts/make_eval_set.py`)

| Part | Source | Labels |
|---|---|---|
| LinkedIn-style posts, job cards, tall feeds (84) | Chromium renders of fictitious content (fake names/companies; no logos) — light/dark, desktop/mobile, some JPEG, 3 with EXIF orientation 6 | source, context, topic, family (narrow group), OCR ground truth from the DOM |
| Chats, code editors, browser articles, settings screens (64) | Chromium renders | context, topics, OCR GT |
| Slides (30), scanned-look letters (20) | Chromium renders; letters get paper tint, rotation, blur, noise | context, OCR GT; slides marked capture-ambiguous |
| Hard negatives | slides/letters/articles that *mention* LinkedIn; prompt-injection text images; black-bar (pillarbox) photos | expected negatives |
| Photos (126) | **real**: TensorFlow `flower_photos` (CC-BY 2.0, attribution in its LICENSE.txt), 5 species × 24; 6 scikit-image sample photos | capture=photo, species = narrow group, COCO objects for 3 skimage photos |
| Near-duplicates | resize 50 % + JPEG q55, WebP q70 of every 6th photo; 75 % JPEG re-encode of 6 screenshots | `near_dup_group` |
| Related, not duplicate | 60 % crops | must not be grouped as duplicates |
| "Movie/TV frames" (30) | **synthetic proxy**: real photos with 2.39:1 letterbox, grade, grain, vignette, burned subtitles; 3 frames per source scene | film=yes, scene group |

Splits are assigned by hashing the *source unit* (post, photo, scene, duplicate family) — variants
never straddle splits: 40 % dev / 60 % test. Identical renders (e.g. repeated slides) collapse to one
asset; the first label wins and conflicts are counted in the report.

**Limitations.** Judgments come from generator labels (no human raters, no disagreement data).
Rendered screenshots are cleaner and more uniform than real captures; the "LinkedIn" UI is a
look-alike; film frames are a proxy; there are no scene positives; object ground truth is 3 images.
Results say *whether the system works end to end and where it fails*, not production accuracy.

## Procedure

1. `make_eval_set.py` → `build_eval_library.py` (import + analyze, 2 workers).
2. `eval_image_library.py --fit-calibration` — per-head logistic calibration on **dev** only.
3. `build_eval_library.py --reanalyze` — only the `context` stage recomputes (cache).
4. `eval_image_library.py --tune` — on **dev** only: decision thresholds (collection: max recall with
   precision floor 0.95 LinkedIn / 0.90 movie; filters: max F1), visual/OCR cut-offs, clustering τ,
   duplicate thresholds → `reports/tuning_dev.json`, `services/organize/decision_thresholds.json`.
5. `build_eval_library.py --reanalyze` (no-op except organize refresh) → `eval_image_library.py`
   on **test** → `reports/evaluation.json`, summarized in `reports/evaluation.md`.

## Metrics

- OCR: CER (order-sensitive, whitespace-normalized), CER ignoring whitespace (isolates word-segmentation),
  word recall (order-insensitive); by category and tag (dark, mobile, tall, re-encoded, scanned).
- Literal search: 60 phrases sampled from test-image ground truth; relevance = every library image
  whose ground truth contains the phrase (boundary-aware); Recall@10; misses split into *OCR miss*
  vs *index miss*.
- Judged queries (visual, OCR meaning, source/context, combined, reference, crop): nDCG@10,
  capped Recall@10 = |top10 ∩ rel| / min(|rel|, 10), P@10; ablations: image-only, OCR-only, hybrid.
- No-relevant queries: number of results returned.
- Heads: precision/recall at 0.5 and 0.8, Brier, ECE (10 bins), reliability table; capture-type
  confusion; LinkedIn as binary.
- Collections: precision/recall vs labels; duplicates: pair precision/recall + mandatory negatives
  (LinkedIn chrome pairs, crops); similarity groups: B-cubed P/R/F1, grouped coverage.
- Latency/RSS: `benchmark_image_library.py`.
