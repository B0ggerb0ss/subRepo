# ADR-004 — Retrieval: typed filters + separate channels + RRF

**Decision.**
1. Explicit grammar (`text: source: object: scene: tag: collection: format: capture: context: topic: after: before: status:`); unknown keys and unsupported values raise useful errors; nothing reaches SQL/FTS unescaped.
2. Hard filters (AND) define eligibility first; channels retrieve inside it: literal phrase (trigram candidates → Python verification with edge-aware word boundaries → char spans mapped to OCR regions), bm25 words (`unicode61`, `tokenchars '+#'`), annotations (bm25), OCR-text semantic (MiniLM cosine over OCR chunks), image-text semantic (CLIP cosine over image views).
3. Region/chunk hits collapse to one candidate per asset **before** fusion; fusion is reciprocal rank `Σ w/(60+rank)` — scores of different kinds are never added. `SearchHit.score` is an ordering score, never shown as a probability.
4. Vectors are compared only within one namespace whose id embeds model digest + preprocessing; a mismatch is refused and shown as degraded. Model changes build a shadow namespace and switch atomically (`promote_ready`, run by the worker after each analysis) once every live asset is covered. Limitation: the previous snapshot is kept but can only be *queried* while its own encoder is provisioned; with only the new model installed, the visual channel is reported as degraded until promotion (lexical/OCR channels keep working).
5. Exact cosine over an in-memory float32 matrix refreshed by namespace revision. ANN deferred until measurements require it (10k-scale p95 in `reports/benchmark.json`).
6. Channel cut-offs (`min_cos`, relative window) are validation-tuned on the dev split (`reports/tuning_dev.json`).

**Literal search and OCR spacing.** PP-OCRv4 sometimes merges words. Multi-word literal phrases fall back to a whitespace-insensitive comparison *only* when no strict match exists for that asset; the evidence says so (`literal_match_ignoring_spaces`) and ranks below strict matches. Raw OCR is never altered.

**Validation.** M2/M3 tests (phrase vs semantic separation, punctuation `c++`/short strings, namespace refusal), `reports/evaluation.md`.
