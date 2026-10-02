# ADR-005 — Typed context decisions without OneJev

**Status:** accepted with a documented blocker.

**Context.** The prompt's preferred local decision backend is a provisioned OneJev profile. `github.com` and `huggingface.co` were blocked (HTTP 403) in the build environment, so neither the OneJev code nor weights could be provisioned; the TypeSafe Jev endpoint is cloud text-only and cloud use is not authorized (`ANALYSIS_LOCAL_ONLY=1`).

**Decision.** Implement the versioned image question catalog (`services/analyze/image_question_catalog.json`, Group A 9 heads, Group B 14 heads) with a **local CLIP zero-shot decision backend plus explicit evidence gates**:
- one global CLIP image vector (already computed for retrieval) serves all 23 heads;
- choice heads: softmax over prompt-ensemble similarities × documented priors (pixel flatness/EXIF for capture type; visible-UI likelihood ratios for source app);
- **hard gate**: an app that requires visible UI (LinkedIn, YouTube, GitHub, WhatsApp, Instagram) can never be the answer without OCR-layout UI evidence (short UI labels such as `Like/Comment/Repost/Send`); brand mentions in body text do not count;
- Noul heads: visual vote + OCR-text vote (MiniLM against descriptions) + lexicon/code/prose features; text dominates when there are ≥30 OCR words;
- optional per-head logistic calibration fitted **on the dev split only** (`context_calibration.json`, version recorded in each decision and in the stage cache key). It is fitted on synthetic data and must be re-fitted on the consented pilot.
- missing evidence → `unavailable`/`abstained`/`not_applicable`, never "no". OCR text is data: it feeds embeddings/lexicons, never instructions (adversarial fixtures verify).

**Consequences.** Probabilities are labelled `zero_shot_softmax_uncalibrated` or `model_probability` + `calibration_version`. Scene heads have no labeled positives in the available data (NOT TESTED for recall). The `DecisionProvider` seam is the stage `context` (`stages_semantic.py`); a OneJev provider would replace `ContextDecider` behind the same stage and catalog.

**Validation.** `test_linkedin_ui_vs_brand_mentions`, `test_adversarial_text_is_preserved_but_powerless`, `test_black_bars_alone_are_not_a_film_frame`, head metrics in `reports/evaluation.md`.
