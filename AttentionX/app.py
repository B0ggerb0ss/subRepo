"""AttentionX — Gradio entrypoint (F11)

Single-process pipeline: normalize → transcribe → energy → face → scene →
segment → score → caption → render 9:16.

Spec reference: Features/F11-gradio-ui/IMPL.md
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gradio as gr

from models.settings import settings
from services.captions import generate_srt
from services.ingest import extract_audio, has_audio_stream, normalize_video
from services.render import render_vertical_clip
from services.scorer import score_candidates
from services.segment_builder import build_candidates
from services.style_profile import build_style_profile
from utils.ffmpeg_utils import get_duration
from utils.io_utils import cleanup_temp, make_session_dirs


# Heavy optional dependencies (faster-whisper, librosa, mediapipe,
# scenedetect) are imported on first use so the image library starts without
# them. The module-level names stay patchable for tests.
def transcribe(wav_path: str, model_size: str = "base"):
    from services.transcribe import transcribe as _transcribe

    return _transcribe(wav_path, model_size=model_size)


def analyze_audio_energy(wav_path: str, percentile: int = 75, merge_gap: float = 0.5):
    from services.audio_features import analyze_audio_energy as _analyze

    return _analyze(wav_path, percentile=percentile, merge_gap=merge_gap)


def track_faces(norm_path: str, sample_fps: float = 2.0):
    from services.face_track import track_faces as _track

    return _track(norm_path, sample_fps=sample_fps)


def detect_scenes(norm_path: str, threshold: float = 27.0):
    from services.scene_detect import detect_scenes as _detect

    return _detect(norm_path, threshold=threshold)

Path("data/temp").mkdir(parents=True, exist_ok=True)
Path("data/outputs").mkdir(parents=True, exist_ok=True)

APP_CSS = """
#attentionx-shell {
  max-width: 1360px;
  margin: 0 auto;
}

#attentionx-outputs .gradio-video {
  min-height: 208px;
}
"""


def _coerce_file_paths(ref_clips: list[Any] | None) -> list[str]:
    """Normalize Gradio file payloads to plain filesystem paths."""
    if not ref_clips:
        return []

    file_paths: list[str] = []
    for item in ref_clips:
        if isinstance(item, str):
            file_paths.append(item)
            continue
        maybe_name = getattr(item, "name", None)
        if isinstance(maybe_name, str):
            file_paths.append(maybe_name)
    return file_paths


def run_pipeline(
    long_video_path: str | None,
    ref_clips: list[Any] | None,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str | None, str | None, str | None, list[str], str]:
    """Execute the full AttentionX pipeline.

    Returns (clip1, clip2, clip3, download_files, status_message).
    Unused clip slots return None (Gradio hides empty Video components).
    """
    if not long_video_path:
        return None, None, None, [], "Error: no video uploaded."

    temp_dir, output_dir = make_session_dirs()
    ref_clip_paths = _coerce_file_paths(ref_clips)

    try:
        progress(0.05, desc="Normalizing video...")
        norm_path = normalize_video(str(long_video_path), temp_dir)

        transcript = []
        energy_peaks = []
        notes: list[str] = []
        if has_audio_stream(norm_path):
            progress(0.10, desc="Extracting audio...")
            wav_path = extract_audio(norm_path, temp_dir)

            progress(0.20, desc="Transcribing speech...")
            transcript = transcribe(wav_path, model_size=settings.whisper_model_size)
            if not transcript:
                notes.append("no speech detected")

            progress(0.35, desc="Analyzing audio energy...")
            energy_peaks, _ = analyze_audio_energy(
                wav_path,
                percentile=settings.rms_peak_percentile,
                merge_gap=settings.rms_merge_gap_sec,
            )
        else:
            notes.append("silent source: ASR and audio energy skipped")

        progress(0.50, desc="Tracking faces...")
        face_track = track_faces(norm_path, sample_fps=settings.face_sample_fps)

        progress(0.60, desc="Detecting scenes...")
        scene_boundaries = detect_scenes(norm_path, threshold=settings.scene_threshold)

        progress(0.65, desc="Building candidate segments...")
        video_duration = get_duration(norm_path)
        candidates = build_candidates(
            transcript=transcript,
            energy_peaks=energy_peaks,
            face_track=face_track,
            scene_boundaries=scene_boundaries,
            video_duration=video_duration,
            min_dur=settings.min_clip_duration,
            max_dur=settings.max_clip_duration,
            target_dur=settings.target_clip_duration,
            snap_tolerance=settings.scene_snap_tolerance,
        )

        progress(0.70, desc="Scoring highlights...")
        style_profile = build_style_profile(ref_clip_paths) if ref_clip_paths else None
        ranked = score_candidates(
            candidates,
            top_n=settings.top_n_clips,
            style_profile=style_profile,
        )

        clip_paths: list[str] = []
        for i, seg in enumerate(ranked):
            progress(0.75 + i * 0.07, desc=f"Rendering clip {i + 1}...")
            srt_path = generate_srt(seg, i, temp_dir)
            clip_path = render_vertical_clip(
                norm_path=norm_path,
                scored_seg=seg,
                srt_path=srt_path,
                face_track=face_track,
                clip_index=i,
                temp_dir=temp_dir,
                output_dir=output_dir,
            )
            clip_paths.append(clip_path)

        progress(1.0, desc="Done.")
        slots = (clip_paths + [None, None, None])[:3]
        status = f"Generated {len(clip_paths)} clip(s)."
        if notes:
            status += " (" + "; ".join(notes) + ")"
        return slots[0], slots[1], slots[2], clip_paths, status

    except Exception as e:
        return None, None, None, [], f"Pipeline error — {type(e).__name__}: {e}"
    finally:
        cleanup_temp(temp_dir)

def build_demo() -> gr.Blocks:
    demo_sample = Path("data/test/test_video.mp4")
    default_video = str(demo_sample) if demo_sample.exists() else None

    with gr.Blocks(title="AttentionX", fill_width=True, css=APP_CSS) as demo:
        gr.Markdown(
            "# AttentionX\n"
            "Upload a long-form video, run the full pipeline, and download up to three 9:16 clips."
        )

        with gr.Row(elem_id="attentionx-shell", equal_height=True):
            with gr.Column(scale=5):
                long_video = gr.Video(
                    label="Upload Long-Form Video",
                    value=default_video,
                    height=260,
                )
                ref_clips_input = gr.File(
                    label="Reference Shorts (optional — for style matching)",
                    file_count="multiple",
                    type="filepath",
                )
                generate_btn = gr.Button("Generate Clips", variant="primary")
                status_box = gr.Textbox(label="Status", interactive=False)

            with gr.Column(scale=7, elem_id="attentionx-outputs"):
                with gr.Row():
                    clip1 = gr.Video(label="Clip 1", height=210)
                    clip2 = gr.Video(label="Clip 2", height=210)
                    clip3 = gr.Video(label="Clip 3", height=210)
                download_files = gr.Files(label="Download All Clips")

        generate_btn.click(
            fn=run_pipeline,
            inputs=[long_video, ref_clips_input],
            outputs=[clip1, clip2, clip3, download_files, status_box],
        )

    return demo


def launch_demo() -> None:
    server_name = os.getenv("ATTENTIONX_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("ATTENTIONX_SERVER_PORT", "7860"))
    prevent_thread_lock = os.getenv("ATTENTIONX_NO_BLOCK", "0") == "1"
    demo.queue(default_concurrency_limit=1).launch(
        server_name=server_name,
        server_port=server_port,
        show_error=True,
        prevent_thread_lock=prevent_thread_lock,
    )


demo = build_demo()

if __name__ == "__main__":
    launch_demo()
