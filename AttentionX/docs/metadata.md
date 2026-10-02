# MediaMetadata/1.1 (images) and 1.2 (videos)

Code: `models/media_metadata.py` (strict Pydantic v2, `extra="forbid"`, no NaN/inf).
The audit's 1.0 contract is vendored unchanged in `models/media_metadata_v1.py`.

## Versioning

- **1.2** (2026-10-02, ADR-011) is written for **video** assets only. It adds the optional `video` and `speech`
  records and optional `frame_id`/`t_s` anchors on OCR regions, object observations and embedding views (new
  view kind `frame_global`). The model rejects these fields in a document that declares 1.1, so a 1.1 reader is
  never handed data it cannot interpret. Image documents are still written as 1.1, unchanged.

- 1.1 is a **new version**, not a loosened 1.0: the strict 1.0 model rejects 1.1 documents
  (tested: `test_metadata_projects_to_strict_v1`).
- `load_metadata(doc)` reads 1.1 directly, or validates a 1.0 document with the strict 1.0 model and
  migrates it. 1.0 OCR carries no polygons, so a migrated document has `stage_status.ocr="missing"`,
  an explicit `migrated_without_geometry` error and `partial=true` — re-running OCR restores geometry.
- `project_to_v1(meta)` is the documented, lossy export projection back to 1.0: identity, technical
  facts, OCR lines as untimed text layers, complete choice/noul decisions (noul confidence = derived
  margin), stage status (`cached→complete`, `disabled→skipped`, `cancelled→error`). Polygons, tiles,
  objects, embeddings and multilabel decisions are dropped. The result validates against the strict
  1.0 model (tested). Exports offer it as `metadata_format="1.0-projection"`.

## Records

| Field | Semantics |
|---|---|
| `image` | stored vs display (EXIF-applied) size and orientation, color mode, ICC flag, animation (frames analyzed), camera-EXIF presence (metadata, not proof), pixel metrics (sharpness, luma quantiles, clipping, edge density, axis-aligned structure, flat-block fraction, colorfulness, letterbox bands), palette, hashes (sha256 of bytes, dHash/pHash of pixels) |
| `ocr` | engine/version/model ids, languages, script scope, tiles (display-space boxes, scale, status), regions (verbatim `raw_text`, `norm_text` search view, normalized display-space polygon, reading order, row group, raw recognizer score), `coverage_fraction`, `complete` + `incomplete_reason` |
| `objects` | detector model, ontology version, storage threshold, observations (label from the model's own label map, normalized box, **raw detector score**) |
| `decisions` | per question id: type, value (None unless complete), full distribution, `probability_kind` (`zero_shot_softmax_uncalibrated`, `model_probability` + `calibration_version`, or `deterministic_parse` for sufficiency heads), status (`complete/abstained/unavailable/not_applicable`), abstain reason, evidence refs, missing evidence, gates (features, visible-UI evidence, priors) |
| `embeddings` | namespace, space, model digest, dim, `l2`, preprocessing version, view (`global_letterbox`, `region`, `ocr_chunk`, `ocr_body`), region box or OCR region refs, storage ref (`sqlite:vectors/...`). Representations, never confidences. |
| `stage_status` / `stage_provenance` | per stage: status and provenance (producer, extractor + version, model digest, confidence kind, cost class, cache key, failure modes) |
| `errors`, `partial` | sanitized stage errors; `partial` must be true iff any stage failed/missed/was partial |
| `video` (1.2) | container, mime, duration, fps, display size (rotation applied), codecs, `has_audio`, `sample_fps`, `keyframe_policy`, `keyframes` (`frame_id`, `t_s`..`t_end_s` span it stands for, managed `frame_ref`, size, `reason` first/content_change/max_gap), `poster_ref`, `coverage_complete` + `coverage_end_s` + `incomplete_reason` |
| `speech` (1.2) | ASR engine/model and verbatim timed segments; present only when local ASR ran (default off) |
| frame anchors (1.2) | `frame_id` + `t_s` on OCR regions, detections and embedding views; polygons/boxes are normalized to **that keyframe** |

Coordinates: normalized to the **display** image (EXIF orientation applied); tiles are in display
pixels before OCR scaling. User annotations, overrides and collection memberships are *not* part of
machine metadata; they live in their own tables and appear in exports.

Video projection to 1.0: keyframe spans become `t_start`/`t_end` of OCR text layers, speech segments become
`asr` text layers, and `technical` carries `duration_s` (tested in `test_m8_video_library.py`).

A real (measured) document from the evaluation library: `docs/examples/metadata_linkedin_post.json`;
a search response: `docs/examples/search_response.json`; an export: `docs/examples/export_snapshot_excerpt.json`.
