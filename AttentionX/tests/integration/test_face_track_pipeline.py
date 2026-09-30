from __future__ import annotations

from services.face_track import track_faces


def test_face_track_falls_back_cleanly_when_no_detector_or_face(no_face_video) -> None:
    track = track_faces(str(no_face_video), sample_fps=1.0)

    assert track.frame_times
    assert track.visibility_ratio == 0.0
    assert set(track.centers_x) == {0.5}
    assert set(track.centers_y) == {0.5}
