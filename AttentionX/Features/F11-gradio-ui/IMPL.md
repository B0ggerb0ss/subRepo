# F11 — Gradio UI — Implementation

## File Location

`app.py`

## Dependencies

- `gradio>=4.0`
- `uuid` (stdlib) — session isolation
- `pathlib` (stdlib)
- All `services/` modules

## App Structure

```python
import gradio as gr
import uuid
from pathlib import Path
from services.ingest import normalize_video, extract_audio
from services.transcribe import transcribe
from services.audio_features import analyze_audio_energy
from services.face_track import track_faces
from services.scene_detect import detect_scenes
from services.segment_builder import build_candidates
from services.scorer import score_candidates
from services.captions import generate_srt
from services.render import render_vertical_clip
from models.settings import Settings


def run_pipeline(long_video_path, ref_clips, progress=gr.Progress()):
    if not long_video_path:
        return [], [], "Error: no video uploaded."
    
    session_id = uuid.uuid4().hex
    temp_dir   = Path("data/temp") / session_id
    output_dir = Path("data/outputs") / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        progress(0.05, desc="Normalizing video...")
        norm_path = normalize_video(str(long_video_path), str(temp_dir))
        
        progress(0.10, desc="Extracting audio...")
        wav_path = extract_audio(norm_path, str(temp_dir))
        
        progress(0.20, desc="Transcribing speech...")
        transcript = transcribe(wav_path)
        
        progress(0.35, desc="Analyzing audio energy...")
        energy_peaks, _ = analyze_audio_energy(wav_path)
        
        progress(0.50, desc="Tracking faces...")
        face_track = track_faces(norm_path)
        
        progress(0.60, desc="Detecting scenes...")
        scene_boundaries = detect_scenes(norm_path)
        
        progress(0.65, desc="Building candidate segments...")
        video_duration = _get_duration(norm_path)
        candidates = build_candidates(transcript, energy_peaks, face_track,
                                      scene_boundaries, video_duration)
        
        progress(0.70, desc="Scoring highlights...")
        style_profile = _build_style_profile(ref_clips) if ref_clips else None
        ranked = score_candidates(candidates, top_n=Settings.top_n_clips,
                                  style_profile=style_profile)
        
        output_paths = []
        for i, seg in enumerate(ranked):
            progress(0.75 + i * 0.07, desc=f"Rendering clip {i+1}...")
            srt_path = generate_srt(seg, i, str(temp_dir))
            clip_path = render_vertical_clip(norm_path, seg, srt_path,
                                             face_track, i, str(temp_dir), str(output_dir))
            output_paths.append(clip_path)
        
        progress(1.0, desc="Done.")
        status = f"Generated {len(output_paths)} clip(s)."
        return output_paths, output_paths, status
    
    except Exception as e:
        return [], [], f"Pipeline error: {type(e).__name__}: {e}"


with gr.Blocks(title="AttentionX") as demo:
    gr.Markdown("# AttentionX\nConvert long-form video into short vertical clips.")
    
    with gr.Row():
        long_video = gr.Video(label="Upload Long-Form Video")
        ref_clips  = gr.File(label="Reference Shorts (optional)", file_count="multiple")
    
    generate_btn = gr.Button("Generate Clips", variant="primary")
    status_box   = gr.Textbox(label="Status", interactive=False)
    
    with gr.Row():
        clip_outputs = [gr.Video(label=f"Clip {i+1}") for i in range(3)]
    
    download_files = gr.Files(label="Download All Clips")
    
    generate_btn.click(
        fn=run_pipeline,
        inputs=[long_video, ref_clips],
        outputs=[*clip_outputs[:1], download_files, status_box],
    )

if __name__ == "__main__":
    demo.launch()
```

## Session Isolation

Each `run_pipeline` call gets a unique `session_id` via `uuid.uuid4().hex`.
Temp files go to `data/temp/{session_id}/`.
Output files go to `data/outputs/{session_id}/`.
This prevents cross-session file collisions in the single-process Gradio server.

## Notes

- The `gr.Progress` context is passed by Gradio automatically when `progress=gr.Progress()` is a default arg.
- `_get_duration()` is a thin wrapper around `ffprobe` to get video duration in seconds.
- `_build_style_profile()` is the F12 integration point; returns `None` if F12 not implemented.
- Output clip list is variable length (1–3); unused `gr.Video` outputs will be empty.
