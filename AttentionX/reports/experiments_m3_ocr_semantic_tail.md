# Experiment (2026-10-02): anchored tail for the OCR-semantic channel — rejected

Hypothesis: on dev, OCR-meaning misses were mostly relevant passages that ranked inside the top-7 by cosine
but fell under the absolute cut-off (`min_cos` 0.38) — e.g. "health checks restarting containers": top cosine
0.392, a relevant article at 0.379 was cut. Change: once a query has one match ≥ `min_cos`, also keep up to
`tail_k` further candidates down to `tail_min_cos`.

Grid on dev only (`min_cos` ∈ {0.34, 0.38}, `rel_window` ∈ {0.25, 0.35}, `tail_k` ∈ {5, 10, 20},
`tail_min_cos` ∈ {0.20, 0.25, 0.30}). The only setting with no loss in another family on dev:
`0.38 / 0.25 / 5 / 0.25` → dev OCR-meaning nDCG 0.751 → 0.778, R@10 0.765 → 0.799; combined, visual, no-relevant
hits unchanged.

Test split (measured once, after choosing on dev):

| family | before nDCG / R@10 | after |
|---|---|---|
| OCR meaning | 0.754 / 0.739 | 0.771 / 0.751 |
| combined | 0.836 / 0.789 | **0.803 / 0.778** |
| others | unchanged | unchanged |

Decision: **not adopted** — the acceptance rule was "dev improves and test does not regress"; combined intent
regressed. The remaining OCR-meaning misses have cosine 0.13–0.31 to the query under MiniLM-L6-v2, i.e. the
limit is the text encoder, not the cut-off. A stronger local text encoder (e.g. bge-small/e5-small ONNX) is the
next step; it cannot be provisioned here (huggingface.co returns 403 through the proxy).
