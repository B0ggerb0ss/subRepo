# AttentionX implementation reference

Companion to `AttentionX_Audit_and_Upgrade_Plan.md`, audited on 30 September 2026. The source was the uploaded AttentionX ZIP and audit brief. This pack proposes an extension of its Python/Gradio app; it does not modify the original app, provision models, deploy services, or implement a complete analyzer.

## Executable parts

- `metadata_models.py`: strict Pydantic v2 MediaMetadata contract and relationship validators.
- `reference_interfaces.py`: stdlib ffprobe, cache hashing, bounded evidence-state construction, API response normalization, Jev/OneJev adapter, contained frame encoding and trim/time projection helpers.
- `test_reference.py`: ten offline contract tests. No live model calls occur during these tests.

Use Python 3.12 and a separate environment with **Pydantic >=2,<3**. The audited reference ran with Pydantic 2.13.5. FFprobe is needed only for `probe_asset` and the optional source-fixture test. Suggested setup when package-network access is available:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'pydantic>=2,<3'
.venv/bin/python -m unittest discover -s . -p 'test_reference.py' -v
```

The bundled-media test skips when the uploaded original source is not available alongside the pack. The other nine tests run using included synthetic contract data. All ten ran and passed in the audit environment with the original source present. These results do not certify the original pytest suite or real OCR/ASR/vision accuracy.

Example schema validation:

```python
from pathlib import Path
from metadata_models import MediaMetadata

metadata = MediaMetadata.model_validate_json(
    Path('talking_head_45s.example.json').read_text(encoding='utf-8')
)
assert metadata.illustrative  # exclude from real inference/cache/benchmark data
```

## Contracts and sketches

`media_metadata_v1.schema.json` is generated from the model. Cross-field invariants such as score expectations, scene order, trim duration and failed-stage partial status require the Python validators in addition to basic JSON Schema validation. `talking_head_45s.example.json` is fully expanded **illustrative** metadata, with synthetic frames/OCR/transcript/probabilities. There are no actual frame image files in this pack. `jev_asset_request.example.json` is syntax/evidence-state demonstration data, not a recorded live request/response or cloud-upload permission.

`question_catalog.json` includes exact options/rubrics for nine asset, eight scene, five text and eight project questions. Dispatch requires evidence gates and explicitly targeted instructions; question IDs are routing keys, not model context. Native System One score levels are zero-based; normalized product levels are one-based. Preserve raw distributions, separate vendor confidence from class probability, and calibrate against held-out labels before automatic actions.

`pipeline_sketch.md` specifies proposed `detect_scenes`, `ocr_frames`, `analyze_asset` orchestration and worker/trim/failure behavior. Its helper names are abstract and **not executable code**. Adapt them into `services/analyze/` using the main report's existing-code insertion map. The pack deliberately does not bundle untested OCR/ASR imports or pretend unavailable native dependencies ran.

The adapter's remote endpoint is allowlisted to the official text-only TypeSafe API and defaults to disallow cloud text. Local OneJev requires a separately provisioned compatible server. Call `decide` only after the application applies flags, applicability and privacy policies; the reference adapter alone is not a full user-authorization, sandbox, retry, tenancy or model-provisioning system. `ANALYSIS_LOCAL_ONLY=1` must prevent selection of any remote adapter, including cloud text. No automatic remote fallback is permitted.

## Audit evidence

`repo_inventory.csv` and `repo_inventory.json` enumerate all 201 original archive files by relative path, role, size and SHA-256. They contain no source-media bytes. `reproductions.json` records focused current-code defects. `validation.md` separates passed offline/FFmpeg checks from unsupported native-model/full-suite checks. No original `.git`, credentials, media files, or runtime caches are shipped in this pack.

The main report contains the complete current-code breakdown, L0–L5 design, pipelines, field producer/cost/failure registry, evaluation budgets, UI plan and two-week daily build order. Proposed production code still needs source integration, dependency locking, native-media tests, language/hardware evaluation, calibration and deployment review.
