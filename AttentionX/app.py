"""AttentionX — Gradio entrypoint (F11)

Single-process pipeline: normalize → transcribe → energy → face → scene →
segment → score → caption → render 9:16.

Spec reference: Features/F11-gradio-ui/IMPL.md
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Local-only by default: no Gradio usage analytics, no Hugging Face Hub calls.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import gradio as gr

from models.schemas import TranscriptionError
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
    normalized_cache: str | None = None,
    known_transcript: list | None = None,
) -> tuple[str | None, str | None, str | None, list[str], str]:
    """Execute the full AttentionX pipeline.

    Returns (clip1, clip2, clip3, download_files, status_message).
    Unused clip slots return None (Gradio hides empty Video components).

    ``normalized_cache``: managed path of this source's normalized proxy; reused
    when present, written (atomically) when absent. ``known_transcript``: speech
    segments already extracted by the library for this exact source; ASR is
    then not run again.
    """
    if not long_video_path:
        return None, None, None, [], "Error: no video uploaded."

    temp_dir, output_dir = make_session_dirs()
    ref_clip_paths = _coerce_file_paths(ref_clips)
    notes: list[str] = []

    try:
        cache = Path(normalized_cache) if normalized_cache else None
        if cache is not None and cache.is_file():
            notes.append("reused the library's normalized source")
            norm_path = str(cache)
        else:
            progress(0.05, desc="Normalizing video...")
            norm_path = normalize_video(str(long_video_path), temp_dir)
            if cache is not None:
                import shutil

                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache.with_suffix(".part")
                shutil.copyfile(norm_path, tmp)
                tmp.replace(cache)

        transcript = []
        energy_peaks = []
        if has_audio_stream(norm_path):
            progress(0.10, desc="Extracting audio...")
            wav_path = extract_audio(norm_path, temp_dir)

            if known_transcript is not None:
                transcript = list(known_transcript)
                notes.append(f"reused the library transcript ({len(transcript)} segment(s))")
            else:
                progress(0.20, desc="Transcribing speech...")
                try:
                    transcript = transcribe(wav_path, model_size=settings.whisper_model_size)
                    if not transcript:
                        notes.append("no speech detected")
                except TranscriptionError as e:
                    # Degrade visibly: clips are chosen from audio/scene/face signals only.
                    transcript = []
                    notes.append(f"{e}; clips chosen without transcript, no captions")

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

_LIBRARY = None


def library_video_choices(lib) -> list[tuple[str, str]]:
    """(label, asset_id) for analyzed-or-pending library videos, newest first."""
    from ui.inspector import clock

    rows = lib.repo.query(
        "SELECT a.id, a.duration_s, (SELECT original_filename FROM import_instances i WHERE i.asset_id=a.id"
        " ORDER BY imported_at LIMIT 1) AS name FROM assets a WHERE a.library_id=? AND a.kind='video'"
        " AND a.deleted_at IS NULL ORDER BY a.created_at DESC, a.id", (lib.cfg.library_id,))
    return [(f"{r['name'] or r['id']} · {clock(r['duration_s'])}", r["id"]) for r in rows]


def generate_from_library(lib, asset_id: str, ref_clips, progress=None):
    """Generate clips from a library video: same five outputs as ``run_pipeline``.

    The managed original is read (never modified); the normalized proxy is cached
    under derived/normalized/ keyed by content hash + normalization recipe, and a
    library transcript of the same bytes is reused instead of re-running ASR.
    """
    from models.schemas import TranscriptSegment
    from services.ingest import NORMALIZE_VERSION
    from services.library.metadata import active_metadata

    asset = lib.get_asset(asset_id)
    if asset is None or asset.kind != "video" or asset.deleted_at is not None:
        return None, None, None, [], "Error: that library video is not available."
    src = lib.path_of(asset.original_ref)
    if src is None:
        return None, None, None, [], "Error: the managed copy of that video is missing."
    import hashlib

    tag = hashlib.sha256(NORMALIZE_VERSION.encode()).hexdigest()[:10]
    h = asset.content_hash
    cache = lib.cfg.derived_root / "normalized" / h[:2] / f"{h}_{tag}.mp4"
    meta = active_metadata(lib.repo, asset_id)
    known = None
    if meta is not None and meta.speech is not None:
        known = [TranscriptSegment(start=s.start_s, end=s.end_s, text=s.text) for s in meta.speech.segments]
    return run_pipeline(str(src), ref_clips, progress=progress or gr.Progress(), normalized_cache=str(cache),
                        known_transcript=known)


def get_library():
    """Process-wide Library (created lazily so importing app has no side effects)."""
    global _LIBRARY
    if _LIBRARY is None:
        from services.library.registry import Library

        _LIBRARY = Library(worker_mode="none")
    return _LIBRARY


def _build_generate_tab() -> None:
    demo_sample = Path("data/test/test_video.mp4")
    default_video = str(demo_sample) if demo_sample.exists() else None

    gr.Markdown("Upload a long-form video, run the full pipeline, and download up to three 9:16 clips.")
    with gr.Row(elem_id="attentionx-shell", equal_height=True):
        with gr.Column(scale=5):
            long_video = gr.Video(
                label="Upload Long-Form Video",
                value=default_video,
                height=260,
            )
            library_pick = gr.Dropdown(label="…or use a video from your library", choices=[], value=None,
                                       allow_custom_value=False, elem_id="ax-gen-library")
            ref_clips_input = gr.File(
                label="Reference Shorts (optional — for style matching)",
                file_count="multiple",
                type="filepath",
            )
            gr.Markdown("_Reference style matching is not implemented yet; uploads are accepted but "
                        "do not change ranking._")
            generate_btn = gr.Button("Generate Clips", variant="primary", elem_id="ax-gen-run")
            status_box = gr.Textbox(label="Status", interactive=False, elem_id="ax-gen-status")

        with gr.Column(scale=7, elem_id="attentionx-outputs"):
            with gr.Row():
                clip1 = gr.Video(label="Clip 1", height=210)
                clip2 = gr.Video(label="Clip 2", height=210)
                clip3 = gr.Video(label="Clip 3", height=210)
            download_files = gr.Files(label="Download All Clips")

    def _generate(video, refs, pick, progress=gr.Progress()):
        if pick:
            return generate_from_library(get_library(), pick, refs, progress)
        return run_pipeline(video, refs, progress)

    generate_btn.click(
        fn=_generate,
        inputs=[long_video, ref_clips_input, library_pick],
        outputs=[clip1, clip2, clip3, download_files, status_box],
        concurrency_limit=1,
    )
    return library_pick


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="AttentionX", fill_width=True, css=APP_CSS) as demo:
        gr.Markdown("# AttentionX")
        with gr.Tabs():
            with gr.Tab("Library", id="library"):
                from ui.library import build_library_tab, gallery_items

                lib = get_library()
                build_library_tab(lib)
                comps = build_library_tab.components
            with gr.Tab("Collections", id="collections") as collections_tab:
                from ui.collections import build_collections_tab

                build_collections_tab(lib, collections_tab)
            with gr.Tab("Generate clips", id="generate") as generate_tab:
                library_pick = _build_generate_tab()
            generate_tab.select(lambda: gr.update(choices=library_video_choices(lib)), None, [library_pick])

        def _initial():
            items, ids = gallery_items(lib, 0)
            return items, ids, f"{lib.count_assets()} item(s) in the library."

        from ui.library import LISTING

        demo.load(_initial, None, [comps["gallery"], comps["ids"], comps["notes"]], **LISTING)

    return demo


def launch_demo() -> None:
    server_name = os.getenv("ATTENTIONX_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("ATTENTIONX_SERVER_PORT", "7860"))
    prevent_thread_lock = os.getenv("ATTENTIONX_NO_BLOCK", "0") == "1"
    lib = get_library()
    if lib.supervisor is None and os.getenv("ATTENTIONX_WORKER", "process") != "none":
        from services.library.worker import WorkerSupervisor

        lib.supervisor = WorkerSupervisor(lib.cfg)
        lib.supervisor.start()
    demo.queue(default_concurrency_limit=4).launch(
        server_name=server_name,
        server_port=server_port,
        # Only derived thumbnails/previews and exports are served; originals never are.
        allowed_paths=[str(lib.cfg.derived_root), str(lib.cfg.exports_root)],
        show_error=True,
        prevent_thread_lock=prevent_thread_lock,
    )


demo = build_demo()

if __name__ == "__main__":
    launch_demo()
