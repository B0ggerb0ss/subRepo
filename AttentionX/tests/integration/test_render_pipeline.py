from __future__ import annotations

from pathlib import Path

from models.schemas import CandidateSegment, FaceTrack, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from services.render import render_vertical_clip
from tests.support.media_factory import ffprobe_json


def test_render_vertical_clip_outputs_h264_916_mp4(source_video: Path, tmp_path: Path) -> None:
    temp_dir = tmp_path / "temp"
    output_dir = tmp_path / "outputs"
    temp_dir.mkdir()
    output_dir.mkdir()

    candidate = CandidateSegment(
        start=0.0,
        end=3.0,
        transcript_text="This render test should produce a browser-playable clip.",
        transcript_segs=[
            TranscriptSegment(0.0, 1.4, "This render test should produce"),
            TranscriptSegment(1.4, 2.8, "a browser-playable clip."),
        ],
        energy_score=0.7,
        face_score=1.0,
        scene_score=1.0,
        duration=3.0,
    )
    scored = ScoredSegment(candidate, 0.8, 0.6, 0.7, 1.0, 1.0, 0.0)
    face_track = FaceTrack(
        frame_times=[0.0, 1.0, 2.0, 3.0],
        centers_x=[0.5, 0.52, 0.5, 0.48],
        centers_y=[0.5, 0.5, 0.5, 0.5],
        visibility_ratio=1.0,
        stability_score=1.0,
    )

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
    video = next(
        stream for stream in streams["streams"] if stream["codec_type"] == "video"
    )

    assert Path(clip_path).exists()
    assert video["codec_name"] == "h264"
    assert int(video["width"]) * 16 == int(video["height"]) * 9
