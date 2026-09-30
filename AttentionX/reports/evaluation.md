# Evaluation report — 2026-09-30

**Read this first.** Measured on the *stand-in* set described in `docs/evaluation-protocol.md`
(Chromium-rendered screenshots of fictitious content + real CC-BY flower photos + scikit-image
photos + synthetic "film" frames), **not** the requested consented 500-image pilot, which was not
available. Relevance and class labels come from the generator; there is no second human rater.
Numbers below are from the **test split** (214 assets) unless marked *dev*; every threshold, cut-off,
calibration and clustering parameter was selected on the dev split (164 assets) only
(`reports/tuning_dev.json`). Raw data: `reports/evaluation.json`.

Hardware: 4 logical CPUs (Intel Xeon @ 2.10 GHz), 16 GB RAM, no GPU; Python 3.11.15, ONNX Runtime 1.30.0, SQLite 3.45.1.
Models: OpenCLIP ViT-B-32/laion2b_s34b_b79k (ONNX), all-MiniLM-L6-v2 (ONNX), EfficientDet-Lite0,
RapidOCR 1.4.4 (PP-OCRv4). Context calibration `platt-synthetic-dev-20260930-f49f053e95`,
thresholds `services/organize/decision_thresholds.json`.

## Scorecard against the provisional targets

| Capability | Target | Measured (test, stand-in) | Status |
|---|---|---|---|
| OCR transcription, clean text | CER ≤ 0.10 | **CER 0.074** (median 0.065, n=47); word recall 0.86 | met on stand-in |
| Literal OCR search | Recall@10 ≥ 0.95 | **0.906** over 60 sampled phrases; 0 index misses, 6 OCR misses, 48 misses where OCR glued the words to neighbours | **below target** (OCR word segmentation) |
| Visual description queries (15) | nDCG@10 ≥ 0.75, R@10 ≥ 0.80 | nDCG **0.86**, R **0.91** (hybrid) | met on stand-in |
| OCR-meaning queries (11) | same | nDCG **0.75**, R **0.74** | nDCG met, **recall below** |
| Source/context queries (10) | same | nDCG **0.89**, R **0.87** | met on stand-in |
| Combined intent (9) | same | nDCG **0.84**, R **0.79** | recall marginally below |
| Reference-image similarity (12) | same | nDCG **0.80**, R **0.79** | recall marginally below |
| Crop similarity (5) | same | nDCG **0.62**, R **0.52** | **below target** |
| Object/scene precision ≥ 0.80 | — | **NOT TESTED** at scale: COCO/Places were unreachable; 3 real photos only (cat, cup, person all detected); scenes have **no positive labels** | NOT TESTED |
| LinkedIn collection | P ≥ 0.95, R ≥ 0.80 | **P 1.00, R 0.90** (look-alike UI; 0 brand-mention/adversarial false positives) | met on stand-in |
| Movie/TV collection | P ≥ 0.90, R ≥ 0.75 | **P 1.00, R 0.73** — synthetic frames share the letterbox+subtitle recipe with two features → optimistic | recall below; not a real film test |
| Near-duplicates | P ≥ 0.98, R ≥ 0.90 | strict labels **P 0.89, R 1.00**; the 4 "false" pairs are same-deck slide re-renders / re-scans of the same letter that the generator never labelled (SSIM ≥ 0.90, identical OCR) → adjudicated P 1.00 | strict: **below**; adjudicated: met |
| Duplicate mandatory negatives | 0 | LinkedIn-chrome false pairs **0**; crop false pairs **0** | met |
| Similarity groups | B-cubed F1 ≥ 0.80 | photos **0.54** (P 0.81/R 0.41, coverage 0.86); film **0.63**; LinkedIn topics **0.35** (P 0.92/R 0.22) | **below target** |
| Corrections / persistence | 0 lost edits | 0 lost in M6 tests + real-browser restart flow | met |

"Met on stand-in" means the gate passes on this data only; it is not a production accuracy claim.

## OCR (test)

| Group | n | CER | CER ignoring spaces | word recall |
|---|---|---|---|---|
| clean (LinkedIn desktop/light, code, article, chat, settings, slide) | 47 | 0.074 | 0.054 | 0.86 |
| dark UI | 20 | 0.079 | 0.062 | 0.87 |
| mobile (incl. EXIF-rotated) | 18 | 0.066 | 0.059 | 0.95 |
| tall feed (3 tiles) | 5 | 0.200 | 0.201 | 0.86 |
| scanned-look letters | 11 | 0.094 | **0.0005** | **0.20** |
| re-encoded 75 % screenshots | 4 | 0.158 | 0.067 | 0.30 |

Reading: characters are recognized well; PP-OCRv4's `ch` recognizer **drops inter-word spaces** on
serif/small text (scans, downscaled copies). The 1.5× OCR scale (ADR-006) fixed this for normal UI
text; the spacing-insensitive literal fallback and the merged-word substring fallback in free-text
search recover many of the remaining cases (29 results in the literal set came through the
fallback, always labelled as such). Tall feeds: CER is order-sensitive and the mobile layout
interleaves short UI labels, so reading order — not recognition — dominates their CER.

## Retrieval ablation (test, nDCG@10 / capped Recall@10)

| Family | hybrid | image-only | OCR-only |
|---|---|---|---|
| visual | 0.86 / 0.91 | **0.92 / 0.94** | 0.00 / 0.00 |
| OCR meaning | **0.75 / 0.74** | 0.62 / 0.52 | 0.73 / 0.69 |
| combined | **0.84 / 0.79** | 0.69 / 0.66 | 0.78 / 0.77 |
| source/context | 0.89 / 0.87 | 0.89 / 0.87 | 0.89 / 0.87 |
| reference | 0.80 / 0.79 | 0.80 / 0.79 | — |
| crop | 0.62 / 0.52 | 0.62 / 0.52 | — |

Hybrid fusion helps text-bearing and combined intents and costs a little on pure visual queries
(lexical/OCR channels add a few text images for words like "flowers"). No-relevant queries now
return 0, 0, 1, 0, 4 results (the 4 are genuine lexical matches of the word *track* in OCR text,
shown with that evidence). Before dev tuning they returned 50 each (stopwords in the lexical OR
query and a too-low OCR-semantic cut-off; both fixed).

## Typed decisions (test)

- `capture_type`: 97.9 % accuracy on decided, non-ambiguous items (1 abstention); 4 photos → graphic.
- `source_app = linkedin` (binary): P 1.00, R 0.90; the slide/letter/article *mentions* of LinkedIn and
  the prompt-injection images never qualify (hard visible-UI gate).
- Calibrated Noul heads (Platt on dev; Brier / ECE): film 0.007 / 0.03, slide 0.009 / 0.01,
  code 0.001 / 0.003, job posting 0.027 / 0.06 (P 1.0, R 0.55 @0.5), article 0.059 / 0.03 (R 0.07 @0.5),
  conversation 0.019 / 0.06.
- Topics are weak: hiring P 0.73 / R 0.36, AI/ML P 1.0 / R 0.53, software P 0.80 / R 0.24,
  education and entertainment **0 / 0** at 0.5. The MiniLM zero-shot text vote contributes little;
  lexicon features carry most of the signal. Needs labeled data or a real decision model (OneJev).
- Scenes: after switching to one softmax with a broad "none of these" set, false positives at 0.5
  dropped from 45 (forest) / 35 (mountain) to 1 / 0 on test (0 / 0 on dev). **Recall is untested.**
- Reliability tables per head are in `evaluation.json → heads.*.reliability`. Calibration was fitted
  on 164 synthetic dev items (6–20 positives per head): re-fit on the pilot before trusting absolute values.

## Dev-set findings that changed the code (all tuning on dev only)

| Finding (dev) | Change |
|---|---|
| OCR merged words on 15 px UI text at 1× | OCR scale 1.5× for 640–1400 px widths (`ocr/1.1`) |
| CLIP "other app" vote overruled visible LinkedIn chrome | visible-UI likelihood ratios + hard gate (`context/1.1-1.2`) |
| First calibration learned shortcuts (`ui_any`, `has_text`) | per-head causal feature sets |
| Same version string for new calibration weights → stale cache | content-hashed calibration/threshold versions |
| CLIP cosine unusable for downscaled small photos (0.79) | near-dup verification by SSIM on 64×64 thumbnails |
| Spurious OCR on photos killed text agreement | text gate only when both sides have ≥ 20 chars |
| UI chrome dominated LinkedIn topic vectors | `ocr_body` vectors without short UI labels |
| Tuning judged relevance over test assets | tuning restricted to dev assets (leak removed) |
| Scene heads fired on flowers | single scene softmax with "none" prompts (`context/1.4`) |
| Generator stored an EXIF-rotated variant sideways | generator fixed (`ImageOps.exif_transpose`) |

## Honest gaps

- The pilot dataset, human relevance judgments and rater agreement do not exist here.
- Object detection and scene recognition are not evaluated for recall/precision at scale.
- Similarity groups (F1 0.35–0.63), crop similarity, topic heads and literal recall on scanned/downscaled
  text are below target. Movie/TV evaluation uses synthetic frames that flatter the model.
- Multilingual OCR/search is unsupported (English/Latin + Simplified Chinese only).
