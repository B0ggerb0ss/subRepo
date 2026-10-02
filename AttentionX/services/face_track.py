"""F05 — Face Detection and Tracking

Spec reference: Features/F05-face-tracking/SPEC.md

Detector resolution order:
1. MediaPipe Tasks FaceDetector with the provisioned BlazeFace model
   (``blaze_face_short_range`` in docs/model-manifest.json).
2. Legacy ``mp.solutions.face_detection`` when an older MediaPipe exposes it.
3. None: every sample is recorded as *not detected* and the track reports
   ``detector_status="missing"`` so callers can tell "no detector" apart from
   "detector found no face".

Detection presence is carried by ``FaceTrack.detected``; coordinates of
undetected samples are the neutral center and must not be read as a detection.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from models.schemas import FaceTrack

log = logging.getLogger(__name__)


def track_faces(norm_path: str, sample_fps: float = 2.0) -> FaceTrack:
    """Sample frames at sample_fps, detect dominant face, return FaceTrack."""
    cap = cv2.VideoCapture(norm_path)
    detector = _build_detector()
    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        interval = max(1, int(round(video_fps / sample_fps)))

        frame_times: list[float] = []
        cx_list: list[float] = []
        cy_list: list[float] = []
        detected: list[bool] = []
        frame_idx = 0

        while True:
            # grab() skips decoding-to-BGR for frames we do not sample.
            if frame_idx % interval != 0:
                if not cap.grab():
                    break
                frame_idx += 1
                continue
            ret, frame = cap.read()
            if not ret:
                break
            pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            t = pos_ms / 1000.0 if pos_ms and pos_ms > 0 else frame_idx / video_fps
            cx, cy, found = _detect_face_center(frame, detector)
            frame_times.append(t)
            cx_list.append(cx)
            cy_list.append(cy)
            detected.append(found)
            frame_idx += 1
    finally:
        cap.release()
        if detector is not None and hasattr(detector, "close"):
            detector.close()

    total = len(frame_times)
    visible = sum(detected)
    visibility_ratio = visible / total if total > 0 else 0.0
    stability_score = _compute_stability(
        [x for x, d in zip(cx_list, detected) if d],
        [y for y, d in zip(cy_list, detected) if d],
    )

    return FaceTrack(
        frame_times=frame_times,
        centers_x=cx_list,
        centers_y=cy_list,
        visibility_ratio=visibility_ratio,
        stability_score=stability_score,
        detected=detected,
        detector_status="available" if detector is not None else "missing",
    )


def _detect_face_center(
    frame: np.ndarray,
    detector: Any | None,
) -> tuple[float, float, bool]:
    if detector is None:
        return 0.5, 0.5, False

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    if isinstance(detector, _TasksFaceDetector):
        box = detector.detect_largest(rgb)
        if box is None:
            return 0.5, 0.5, False
        x, y, bw, bh = box
        return float((x + bw / 2) / w), float((y + bh / 2) / h), True

    result = detector.process(rgb)
    if result.detections:
        bbox = result.detections[0].location_data.relative_bounding_box
        return float(bbox.xmin + bbox.width / 2), float(bbox.ymin + bbox.height / 2), True
    return 0.5, 0.5, False


def _compute_stability(cx_list: list[float], cy_list: list[float]) -> float:
    if len(cx_list) < 2:
        return 1.0
    var_x = float(np.var(cx_list))
    var_y = float(np.var(cy_list))
    return float(max(0.0, 1.0 - min(1.0, (var_x + var_y) * 10)))


class _TasksFaceDetector:
    def __init__(self, model_path: Path, min_confidence: float = 0.5) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            min_detection_confidence=min_confidence,
        )
        self._mp_image_cls = __import__("mediapipe").Image
        self._mp_format = __import__("mediapipe").ImageFormat.SRGB
        self._detector = vision.FaceDetector.create_from_options(options)

    def detect_largest(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        image = self._mp_image_cls(image_format=self._mp_format, data=np.ascontiguousarray(rgb))
        result = self._detector.detect(image)
        if not result.detections:
            return None
        best = max(result.detections, key=lambda d: d.bounding_box.width * d.bounding_box.height)
        b = best.bounding_box
        return b.origin_x, b.origin_y, b.width, b.height

    def close(self) -> None:
        self._detector.close()


def _build_detector() -> Any | None:
    try:
        import mediapipe as mp
    except Exception:
        return None

    try:
        from services.library.config import get_config

        model_path = get_config().model_path("blaze_face_short_range")
        if model_path is not None:
            return _TasksFaceDetector(model_path)
    except Exception as e:  # provisioned-model load failures fall through, visibly
        log.warning("MediaPipe Tasks face detector unavailable: %s", type(e).__name__)

    solutions = getattr(mp, "solutions", None)
    if solutions is None or not hasattr(solutions, "face_detection"):
        return None
    return solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.5,
    )
