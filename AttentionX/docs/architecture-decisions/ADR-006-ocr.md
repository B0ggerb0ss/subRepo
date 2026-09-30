# ADR-006 — OCR engine, tiling and scale policy

**Decision.** RapidOCR (`rapidocr_onnxruntime==1.4.4`, PP-OCRv4 det/rec + mobile cls ONNX shipped in the wheel, sha256-pinned and verified at load) behind `services/analyze/ocr.py`. Tesseract (apt `tesseract-ocr-eng`) is an *explicit* fallback recorded in provenance. Missing weights → stage `missing` with `ocr_model_missing`, never an empty success.

**Tiling.** Display-oriented image covered by overlapping tiles (1280 px, 160 px overlap) at scale ≥ 1 for typical screenshot widths; bounded by `ocr_max_tiles` and `ocr_max_seconds` with coverage recorded (`complete=false` + reason). Overlap duplicates are merged only across different tiles when boxes coincide (≥60% of the smaller box) *and* one text contains the other; repeated legitimate lines at other positions survive. Reading order: rows by vertical overlap, then x.

**Scale 1.5× for 640–1400 px wide images.** Measured: PP-OCRv4's `ch` recognizer drops inter-word spaces on ~15 px UI text at 1×; 1.5× restores them (fixture CER 0.072 → 0.067 with correct spacing) at ≈1.5× OCR time. Downscaled copies remain imperfect → spacing-insensitive literal fallback (ADR-004).

**Scripts.** English/Latin (+ Simplified Chinese) only. Arabic/Devanagari are unsupported and reported as such (`ocr_language_unsupported`) — never silently recognized with the wrong model.
