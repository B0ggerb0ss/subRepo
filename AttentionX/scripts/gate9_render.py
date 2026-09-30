"""Gate 9 — Render validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import check, summarize
from models.schemas import CandidateSegment, FaceTrack, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from services.render import render_vertical_clip
from tests.support.media_factory import ffprobe_json, make_testsrc_video


def main() -> int:
    print("\n=== Gate 9 — Render ===\n")
    with tempfile.TemporaryDirectory(prefix="attentionx_gate9_") as tmp:
        tmp_path = Path(tmp)
        source_video = make_testsrc_video(tmp_path / "source.mp4", duration=4.0)
        candidate = CandidateSegment(
            start=0.0,
            end=3.0,
            transcript_text="render gate",
            transcript_segs=[
                TranscriptSegment(0.0, 1.4, "Render gate line one."),
                TranscriptSegment(1.4, 2.7, "Render gate line two."),
            ],
            energy_score=0.8,
            face_score=1.0,
            scene_score=1.0,
            duration=3.0,
        )
        scored = ScoredSegment(candidate, 0.0, 0.0, 0.8, 1.0, 1.0, 0.0)
        face_track = FaceTrack(
            frame_times=[0.0, 1.0, 2.0, 3.0],
            centers_x=[0.5, 0.52, 0.5, 0.48],
            centers_y=[0.5, 0.5, 0.5, 0.5],
            visibility_ratio=1.0,
            stability_score=1.0,
        )
        temp_dir = tmp_path / "temp"
        output_dir = tmp_path / "outputs"
        temp_dir.mkdir()
        output_dir.mkdir()
        srt_path = generate_srt(scored, 0, str(temp_dir))
        clip_path = render_vertical_clip(
            norm_path=str(source_video),
            scored_seg=scored,
            srt_path=srt_path,
            face_track=face_track,
            clip_index=0,
            temp_dir=str(temp_dir),
            output_dir=str(output_dir),
        )
        streams = ffprobe_json(clip_path, "stream=codec_type,codec_name,width,height")
        video = next(stream for stream in streams["streams"] if stream["codec_type"] == "video")
        audio = next(stream for stream in streams["streams"] if stream["codec_type"] == "audio")
        clip_exists = Path(clip_path).exists()

    results = [
        check("rendered clip exists", lambda: clip_exists or (_ for _ in ()).throw(RuntimeError("clip missing"))),
        check(
            "output aspect ratio is 9:16",
            lambda: int(video["width"]) * 16 == int(video["height"]) * 9
            or (_ for _ in ()).throw(RuntimeError(f"got {video['width']}x{video['height']}")),
        ),
        check(
            "output remains browser-playable",
            lambda: video["codec_name"] == "h264" and audio["codec_name"] == "aac"
            or (_ for _ in ()).throw(RuntimeError(f"video={video['codec_name']} audio={audio['codec_name']}")),
        ),
    ]
    return summarize(9, results)


if __name__ == "__main__":
    sys.exit(main())
