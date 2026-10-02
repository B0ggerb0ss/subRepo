# F11 — Gradio UI

## Purpose

Wire the full pipeline into a browser-accessible Gradio interface. The UI handles
upload, pipeline trigger, status display, clip preview, and file download.
This is the only user-facing surface in the MVP; no separate frontend or API is needed.

## Inputs (via UI components)

| Component     | Type           | Description                                    |
|---------------|----------------|------------------------------------------------|
| long_video    | gr.Video       | Single long-form video upload                  |
| ref_clips     | gr.File        | Optional: multiple reference short clips       |
| generate_btn  | gr.Button      | Triggers the full pipeline                     |

## Outputs (via UI components)

| Component     | Type           | Description                                    |
|---------------|----------------|------------------------------------------------|
| clip_gallery  | list[gr.Video] | Up to 3 rendered vertical clips, playable      |
| download_files| gr.Files       | Downloadable links for all output clips        |
| status_log    | gr.Textbox     | Pipeline stage status messages                 |
| score_table   | gr.Dataframe   | Score breakdown for each clip (optional)       |

## User Flow

1. User uploads a long-form video via `gr.Video`.
2. User optionally uploads reference clips via `gr.File(file_count="multiple")`.
3. User clicks **Generate Clips**.
4. Status log updates as each pipeline stage completes.
5. Output clips appear as playable videos with download links.
6. Score breakdown table shows per-clip scoring details.

## Input Validation

- Accepted video formats: MP4, MOV, AVI, MKV, WebM
- Maximum file size: 500 MB (configurable in `Settings.max_upload_mb`)
- If no video uploaded: show error, do not run pipeline

## Error Display

- Pipeline exceptions → displayed in `status_log` as readable messages
- Never show raw tracebacks to users
- Always show a human-readable summary of what went wrong

## Constraints

- All UI logic lives in `app.py` only.
- No UI logic in `services/`.
- The pipeline function called by Gradio must be a single callable that returns all outputs.
- Use `gr.Progress` for stage-level status updates during processing.
- Session isolation: use a unique temp directory per submission to avoid cross-session file conflicts.
