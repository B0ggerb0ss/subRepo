# Verified current state (M0) — audit reconciliation

Checked on 2026-09-30 against the uploaded `AttentionX.zip` (imported verbatim in commit
"Import AttentionX source from uploaded archive (unmodified)") and this environment.

## Environment actually used

| Item | Observed |
|---|---|
| Hardware | 4 logical CPUs, 15 GiB RAM, no GPU (container) — *below* the prompt's 8-core/16 GB target profile |
| Python / SQLite | 3.11.15 / 3.45.1 (FTS5 + trigram available) |
| System tools | ffmpeg 6.1.1, tesseract 5.3.4 + eng, libEGL (installed via apt; recorded in `packages.txt`) |
| Network | PyPI, Ubuntu archive, GCS, Jina S3 reachable; **huggingface.co, github.com releases, download.pytorch.org, images.cocodataset.org, Places365 blocked (403)** |
| Archive `.git` | tracks only `.gitignore` and `README.md`; all runtime files untracked (audit finding confirmed) |

## Audit findings — reconciled

| Audit finding | Verified at | Status now |
|---|---|---|
| No durable asset/metadata/search model | `app.py`, `models/schemas.py`, `utils/io_utils.py` (session temp dirs only) | **Resolved**: `services/library/*`, `models/media_metadata.py` |
| Whole-source normalization, sequential passes | `app.py:run_pipeline` → `services/ingest.py:normalize_video`, `face_track.py:track_faces`, `scene_detect.py:detect_scenes` each decode | **Partly**: image path never transcodes; video path unchanged apart from fixes (shared video metadata = remaining work, see feature-status) |
| Silent video rejected; empty ASR fatal | `ingest.py:normalize_video` (audio check), `transcribe.py:transcribe` (`raise ... no speech`) | **Resolved** (ADR-007) |
| Whisper constructed per run; eager imports | `transcribe.py:transcribe`, `app.py` top-level imports | **Resolved**: lazy import + per-process cache; `app.py` imports without faster-whisper |
| No image import/OCR/embeddings/objects/clusters | runtime source | **Implemented** (M1–M5) |
| Snap exceeds max; silence absorbed | `segment_builder.py:build_candidates/_chunk_transcript` | **Resolved** (reproduced: 21 s window with max 20; window [15,25) with speech at 20) |
| Center coords as absence | `segment_builder.py:_face_in_window`, `render.py:_mean_face_cx`, `face_track.py` | **Resolved** (`FaceTrack.detected`) |
| Caption loss/overflow | `captions.py:generate_srt` (`[:2]` lines, no clamp) | **Resolved** |
| Narrow portrait crop failure | `render.py:render_vertical_clip` | **Resolved** (crop-or-pad) |
| No lock / native suite / real accuracy | `requirements.txt` | `requirements.lock` + native tests added; accuracy measured on a synthetic+real stand-in set only |
| Style/Gemini stubs | `style_profile.py`, `gemini_hooks.py` | Still stubs — now labelled in the UI ("not implemented yet"); not extended |
| Deploy pushes HEAD with untracked runtime | `deploy_to_hf.sh` | Unchanged and **not run** (no deployment authorized) |

## Additional finding (not in the audit)

The installed `mediapipe==1.0.1` has no `mp.solutions`; the original `face_track._build_detector`
therefore always returned `None` and **no face was ever detected** — every crop silently used the
center fallback. Fixed with the MediaPipe Tasks detector (needs `libEGL`).

## Baseline tests

`bash run_tests.sh all` on the unmodified import: **26 passed** once `faster-whisper` (library only)
is installed; without it, collection fails (`ModuleNotFoundError: faster_whisper` from `app.py`).
All original tests use generated media and mocked transcription — they are not ASR/vision accuracy evidence.

The five-value Generate contract `(clip1, clip2, clip3, download_files, status)` is preserved and
covered by `tests/unit/test_app.py` and `tests/integration/test_app_pipeline.py`.
