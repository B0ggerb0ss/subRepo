"""Grounded object detection: one small fixed-vocabulary baseline.

EfficientDet-Lite0 (MediaPipe Tasks ObjectDetector, COCO labels embedded in
the model's own metadata; the 90-slot map has '???' holes, so labels are read
from the model, never assumed dense). Scores are raw detector scores — not
calibrated probabilities. The small COCO taxonomy is a baseline, not
open-world recognition: unsupported words are rejected by the search filter
and offered as approximate semantic search instead.
"""
from __future__ import annotations

import numpy as np

from services.analyze.catalog import OBJECT_ONTOLOGY, model_label_map
from services.analyze.providers import ProviderUnavailable
from services.library.config import LibraryConfig

OBJECTS_VERSION = "objects/1.0"
STORE_THRESHOLD = 0.30     # observations kept (raw score); filters use catalog object_threshold
MAX_RESULTS = 25


class ObjectDetector:
    def __init__(self, model_path: str, labels: list[str]) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        opts = vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            score_threshold=STORE_THRESHOLD,
            max_results=MAX_RESULTS,
        )
        self._mp = mp
        self._det = vision.ObjectDetector.create_from_options(opts)
        self.labels = labels
        self.model = "efficientdet_lite0"
        self.ontology_version = OBJECT_ONTOLOGY

    @classmethod
    def load(cls, cfg: LibraryConfig) -> "ObjectDetector":
        p = cfg.model_path("efficientdet_lite0")
        labels = model_label_map(cfg)
        if p is None or not labels:
            raise ProviderUnavailable("model_missing", "efficientdet_lite0 not provisioned (scripts/provision_models.py)")
        try:
            import mediapipe  # noqa: F401
        except Exception as e:
            raise ProviderUnavailable("engine_missing", "mediapipe is not installed") from e
        try:
            return cls(str(p), labels)
        except Exception as e:
            raise ProviderUnavailable("model_load_error", f"object detector failed to load: {type(e).__name__}") from e

    def close(self) -> None:
        self._det.close()

    def detect(self, rgb: np.ndarray) -> list[dict]:
        h, w = rgb.shape[:2]
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._det.detect(image)
        out = []
        for i, d in enumerate(result.detections):
            cat = d.categories[0]
            idx = cat.index if isinstance(cat.index, int) else None
            label = cat.category_name or (self.labels[idx] if idx is not None and 0 <= idx < len(self.labels) else None)
            if not label or label == "???":
                continue
            b = d.bounding_box
            x0, y0 = max(0.0, b.origin_x / w), max(0.0, b.origin_y / h)
            x1, y1 = min(1.0, (b.origin_x + b.width) / w), min(1.0, (b.origin_y + b.height) / h)
            if x1 <= x0 or y1 <= y0:
                continue
            out.append({"obs_id": f"o{i:03d}", "label": label, "class_id": idx if idx is not None else (self.labels.index(label) if label in self.labels else None),
                        "box": [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)],
                        "detector_score": round(float(cat.score), 5)})
        return out
