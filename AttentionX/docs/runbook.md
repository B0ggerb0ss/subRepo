# AttentionX media library — runbook

All commands run from `AttentionX/`.

## 1. Install

```bash
sudo apt-get install -y $(cat packages.txt)          # ffmpeg, tesseract-ocr(-eng), libegl1, libgles2, fonts
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt                    # or: pip install -r requirements.lock
```

`requirements.lock` is the exact set this build was tested with (Python 3.11.15).

## 2. Provision models (the only step that uses the network for models)

```bash
python scripts/provision_models.py                     # download + verify sha256/md5, write PROVISIONED.json
python scripts/provision_models.py --check --deep      # re-hash what is on disk
python scripts/provision_models.py --capabilities      # what the running config can do
python scripts/provision_models.py --from-dir /media/usb/models   # offline: verify local copies instead
```

Models land in `data/models/<name>/` (override: `ATTENTIONX_MODEL_ROOT`). Nothing is downloaded
during analysis or search. After provisioning, the app runs with networking disabled.

Unavailable in this build (documented, not faked): OneJev (typed decisions use the CLIP zero-shot
backend, ADR-005), Whisper weights (ASR off), non-Latin OCR scripts.

## 3. Run

```bash
python app.py                     # http://127.0.0.1:7860 — Library, Collections, Generate clips tabs
```

| Variable | Default | Meaning |
|---|---|---|
| `ATTENTIONX_LIBRARY_ROOT` | `data/library` | library database, originals, derived files, exports |
| `ATTENTIONX_WORKER` | `process` | `process` (spawned worker), `thread`, `none` |
| `ATTENTIONX_SERVER_NAME` / `_PORT` | `127.0.0.1` / `7860` | loopback by default; do not expose without auth |
| `ANALYSIS_OCR`, `ANALYSIS_EMBEDDINGS`, `ANALYSIS_OCR_TEXT_EMBEDDINGS`, `ANALYSIS_OBJECTS`, `ANALYSIS_CONTEXT`, `ANALYSIS_CLUSTERING` | `1` | feature flags; `0` shows the stage as *disabled* |
| `ANALYSIS_OCR_TESSERACT_FALLBACK` | `1` | explicit, recorded fallback when RapidOCR is unavailable |
| `ANALYSIS_LOCAL_ONLY` | `1` | forbids any cloud adapter; `ANALYSIS_ALLOW_CLOUD_*` must stay `0` with it |
| `ANALYSIS_OCR_LANGUAGES` | `en` | `en`/`ch` via RapidOCR; others only via Tesseract language data if installed |
| `LIBRARY_MAX_IMAGE_MB`, `LIBRARY_MAX_IMAGE_MEGAPIXELS`, `LIBRARY_OCR_MAX_TILES` | 50, 40, 24 | admission and OCR bounds |
| `LIBRARY_MAX_VIDEO_MB`, `LIBRARY_MAX_VIDEO_MINUTES`, `LIBRARY_VIDEO_MAX_KEYFRAMES` | 4096, 180, 120 | video admission and keyframe budget (spread over the whole duration; the effective spacing is recorded as `video.min_gap_s`) |
| `ANALYSIS_ASR` | `0` | speech transcription for library videos; needs locally provisioned Whisper weights (`ATTENTIONX_WHISPER_DIR`), never downloads |

Videos (MP4/MOV/M4V/WebM/MKV) are imported through the same Import box or folder import. They are analyzed
via sampled keyframes (ADR-011), and their text is searchable with a timestamp. The **Generate clips** tab can
use a library video directly; its normalized proxy is cached under `derived/normalized/`.

## 4. CLI

```bash
python scripts/library_cli.py import  ~/Pictures/screens/*.png
python scripts/library_cli.py import-folder ~/Pictures/screens
python scripts/library_cli.py analyze                 # run queued jobs inline
python scripts/library_cli.py search 'source:linkedin text:"hiring"'
python scripts/library_cli.py similar ast_…  [--crop 0.1,0.1,0.6,0.6]
python scripts/library_cli.py collections
python scripts/library_cli.py refresh                  # rebuild similarity groups + duplicate candidates
python scripts/library_cli.py export [--collection linkedin_screenshots] [--v1]
python scripts/library_cli.py status
```

## 5. Query grammar

`text:"exact phrase"`, `source:linkedin`, `object:car`, `scene:beach`, `tag:mine`,
`collection:<key|id|label>`, `format:png|mp4|webm`, `type:image|video`, `capture:screenshot`, `context:source_code`,
`topic:ai_ml`, `after:2026-01-01`, `before:…`, `status:partial`; everything else is free-text intent
(lexical + OCR meaning + visual). Filters combine with AND. Unknown filters, unsupported object
labels and negated filters return an explanatory error.

## 6. Failure and recovery policy

| Situation | Behavior |
|---|---|
| Unsupported/corrupt/oversized/decompression-bomb file | rejected at admission with a sanitized code, or (decode failure) asset shows `error` on the pixels stage; the rest of the batch continues |
| Missing OCR weights / engine | OCR stage `missing` (`ocr_model_missing`), asset `partial`; provision, then **Retry analysis** — only the failed stage re-runs |
| Missing CLIP/MiniLM/detector | those stages `missing`; lexical and manual workflows keep working; search shows a degraded notice |
| Worker crash / app restart | `Library.recover()` requeues interrupted jobs (lease), fails them visibly after 3 attempts; temp debris removed; orphan originals only reported |
| Cancel | queued jobs cancel immediately; running jobs stop at the next stage boundary (hard stop: worker restart) |
| Late/stale job | cannot activate metadata (generation fencing) → `superseded` |
| Delete | tombstone: immediately ineligible for every search channel; the managed copy stays until purged; your source file is never touched |
| Disk/DB write failure | nothing reports success before the authoritative commit; stage cache rows are idempotent |
| Video too long/large, no video stream, unreadable container | rejected at admission (`too_long`, `too_large`, `no_video_stream`, `corrupt_video`) |
| Long or busy video | the keyframe budget is spread over the whole video (sparser sampling, complete coverage); if the cap is still hit, `coverage_complete=false` with the reason and the asset is `partial` |
| Cloud | none. There is no hidden cloud fallback. |

Logs contain job/stage ids and exception types, not OCR text, keys or filenames.

## 7. Evaluate and benchmark

```bash
python scripts/make_eval_set.py                  # needs data/eval_sources/flower_photos (TF flowers, CC-BY)
python scripts/build_eval_library.py             # import + analyze with 2 workers
python scripts/eval_image_library.py --fit-calibration   # dev split only
python scripts/build_eval_library.py --reanalyze # re-runs only the context stage (cache)
python scripts/eval_image_library.py --tune      # dev split sweeps -> reports/tuning_dev.json
python scripts/eval_image_library.py             # test split -> reports/evaluation.json
python scripts/benchmark_image_library.py        # -> reports/benchmark.json
```

## 8. Upgrades and migrations

The database schema is migrated forward automatically on open (`PRAGMA user_version`; v6 adds the video columns:
`assets.duration_s`, and `frame_id`/`t_s` on `ocr_regions`, `object_observations`, `vectors`). Migrations only
add columns or tables. Back up `library.sqlite3` (plus `-wal`) before upgrading. A database newer than the
build is refused, never down-migrated. Existing image metadata revisions (1.1) are read unchanged; no
re-analysis is needed.

## 9. Tests

```bash
bash run_tests.sh all     # unit + integration (real FFmpeg, RapidOCR, ONNX models)
bash run_tests.sh e2e     # real Chromium against the running app
```
