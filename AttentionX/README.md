---
title: AttentionX
emoji: "🎬"
colorFrom: blue
colorTo: red
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
short_description: Local image library searchable by its contents, plus long-video to 9:16 clips.
---

# AttentionX

A local, offline-capable **media library that makes images and screenshots searchable by what
they actually contain**, next to the original **long-video → captioned 9:16 clips** generator.

- Find an image by text *inside* it (`text:"feature store"`), even with a meaningless filename —
  and see the exact highlighted region.
- Search by description (`rainy street at night`), by OCR meaning (`posts discussing train-serving
  skew`), by detected object (`object:cat`), by visible app UI (`source:linkedin text:"hiring"`), or
  by a reference image / crop.
- Browse evidence-backed smart sets (LinkedIn screenshots → job / technical / general posts, movie/TV
  frames, code, slides, documents, conversations, "needs review"), similarity groups inside them, and
  near-duplicate candidates (never auto-deleted).
- Correct anything — rename/merge/split/pin groups, move/exclude members, override a decision — and
  the correction survives re-analysis, reclustering and restarts. Export versioned snapshots.
- Every stage says honestly whether it is complete, cached, partial, missing, disabled or failed.

Status, evidence and known gaps: [`docs/feature-status.md`](docs/feature-status.md).
Measured quality (on a stand-in set, not the consented pilot): [`reports/evaluation.md`](reports/evaluation.md).

## Quick start

```bash
sudo apt-get install -y $(cat packages.txt)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/provision_models.py      # explicit, pinned, hash-verified; the only model download
python app.py                           # http://127.0.0.1:7860
```

Full operating guide: [`docs/runbook.md`](docs/runbook.md) · user walkthrough:
[`docs/walkthrough.md`](docs/walkthrough.md) · architecture decisions: [`docs/architecture-decisions/`](docs/architecture-decisions/).

## Tests

```bash
bash run_tests.sh all    # unit + integration: real FFmpeg, RapidOCR, ONNX CLIP/MiniLM, EfficientDet, SQLite
bash run_tests.sh e2e    # real Chromium against the running app
```

## Layout

```
app.py                      Gradio entry: Library, Collections, Generate clips tabs
models/                     media_metadata (1.1 + 1.0 loader/projection), asset, search, collections
services/library/           config, repository (SQLite), ingest, jobs, worker, metadata, registry, export
services/analyze/           pixels, ocr, embeddings, objects, context, pipeline, cache, providers, catalog
services/search/            parser, lexical (FTS5), vectors, service (fusion + evidence)
services/organize/          collections (smart sets), clustering, duplicates, overrides, service
services/*.py               legacy video pipeline (ingest, transcribe, render, captions, ...)
ui/                         library, inspector, collections tabs
scripts/                    provision_models, library_cli, make_eval_set, build_eval_library,
                            eval_image_library, benchmark_image_library, legacy gates
docs/                       runbook, feature-status, evaluation protocol, ADRs, model manifest
```

## Legacy video workflow

The **Generate clips** tab keeps the original contract (three clip slots, downloads, status). Fixes:
exact-range renders, captions that keep every word inside the clip, crop-or-pad for narrow sources,
silent videos accepted, faces actually detected again. ASR needs Whisper weights provisioned
separately (not available in this build environment) and is never downloaded implicitly; without
them, Generate still produces clips from audio/scene/face signals and the status says
"ASR unavailable … clips chosen without transcript, no captions".

Hugging Face deployment (`deploy_to_hf.sh`) is unchanged and was not run.
