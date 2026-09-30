"""F05 — Face Detection and Tracking

Spec reference: Features/F05-face-tracking/SPEC.md
"""
from __future__ import annotations

from typing import Any

import cv2
import mediapipe as mp
import numpy as np

from models.schemas import FaceTrack


def track_faces(norm_path: str, sample_fps: float = 2.0) -> FaceTrack:
    """Sample frames at sample_fps, detect dominant face, return FaceTrack.

    Always returns a valid FaceTrack. Frames with no detection use center (0.5, 0.5).
    """
    cap = cv2.VideoCapture(norm_path)
    detector = _build_detector()
    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        interval = max(1, int(video_fps / sample_fps))

        frame_times: list[float] = []
        cx_list: list[float] = []
        cy_list: list[float] = []
        visible_count = 0
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % interval == 0:
                t = frame_idx / video_fps
                cx, cy, detected = _detect_face_center(frame, detector)
                frame_times.append(t)
                cx_list.append(cx)
                cy_list.append(cy)
                if detected:
                    visible_count += 1
            frame_idx += 1
    finally:
        cap.release()
        if detector is not None and hasattr(detector, "close"):
            detector.close()

    total = len(frame_times)
    visibility_ratio = visible_count / total if total > 0 else 0.0
    stability_score = _compute_stability(cx_list, cy_list)

    return FaceTrack(
        frame_times=frame_times,
        centers_x=cx_list,
        centers_y=cy_list,
        visibility_ratio=visibility_ratio,
        stability_score=stability_score,
    )


def _detect_face_center(
    frame: np.ndarray,
    detector: Any | None,
) -> tuple[float, float, bool]:
    if detector is None:
        return 0.5, 0.5, False

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = detector.process(rgb)
    if result.detections:
        bbox = result.detections[0].location_data.relative_bounding_box
        cx = bbox.xmin + bbox.width / 2
        cy = bbox.ymin + bbox.height / 2
        return float(cx), float(cy), True
    return 0.5, 0.5, False


def _compute_stability(cx_list: list[float], cy_list: list[float]) -> float:
    if len(cx_list) < 2:
        return 1.0
    var_x = float(np.var(cx_list))
    var_y = float(np.var(cy_list))
    return float(max(0.0, 1.0 - min(1.0, (var_x + var_y) * 10)))


def _build_detector() -> Any | None:
    """Return a MediaPipe face detector when the legacy API is available.

    Newer MediaPipe wheels may expose only `mediapipe.tasks` at the top level.
    AttentionX can still satisfy its crop contract without a detector by using
    the required center-crop fallback.
    """
    solutions = getattr(mp, "solutions", None)
    if solutions is None or not hasattr(solutions, "face_detection"):
        return None

    return solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.5,
    )
