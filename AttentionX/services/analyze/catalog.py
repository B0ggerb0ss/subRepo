"""Versioned image question catalog + object vocabulary helpers."""
from __future__ import annotations

import json
import zipfile
from functools import lru_cache
from pathlib import Path

from services.library.config import LibraryConfig

CATALOG_PATH = Path(__file__).with_name("image_question_catalog.json")
OBJECT_ONTOLOGY = "coco2017-efficientdet-lite0-labels/1"

# Aliases map user words onto supported detector labels only; they never add
# new vocabulary.
OBJECT_ALIASES = {
    "people": "person", "man": "person", "woman": "person", "human": "person",
    "automobile": "car", "bike": "bicycle", "motorbike": "motorcycle", "plane": "airplane",
    "aeroplane": "airplane", "tv": "tv", "television": "tv", "monitor": "tv", "sofa": "couch",
    "cellphone": "cell phone", "phone": "cell phone", "mobile": "cell phone",
    "table": "dining table", "puppy": "dog", "kitten": "cat", "cup": "cup", "mug": "cup",
}


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    questions = {}
    for gname, g in data["groups"].items():
        for qid, q in g["questions"].items():
            questions[qid] = dict(q, group=gname)
    data["questions"] = questions
    data.setdefault("object_threshold", 0.5)
    return data


def group_heads(group: str) -> list[str]:
    return list(catalog()["groups"][group]["questions"])


_FILTER_PREFIX = {"scene": "scene.", "context": "context.", "topic": "topic."}


def FILTER_QUESTION(key: str, value: str) -> tuple[str, str]:  # noqa: N802 - table-like helper
    """Map a query filter to (question_id, expected value). Raises ValueError for unsupported values."""
    from services.search.service import SearchError

    q = catalog()["questions"]
    if key == "capture":
        opts = q["capture_type"]["options"]
        if value not in opts:
            raise SearchError(f"capture:{value} unsupported; use one of {sorted(opts)}")
        return "capture_type", value
    if key == "source":
        opts = q["source_app"]["options"]
        if value not in opts:
            raise SearchError(f"source:{value} unsupported; use one of {sorted(opts)}")
        return "source_app", value
    prefix = _FILTER_PREFIX.get(key)
    if prefix:
        qid = prefix + value.replace(" ", "_")
        if qid not in q:
            options = sorted(k[len(prefix):] for k in q if k.startswith(prefix))
            raise SearchError(f"{key}:{value} unsupported; use one of {options}")
        return qid, "yes"
    raise SearchError(f"unsupported filter {key}")


@lru_cache(maxsize=4)
def _labels_from_model(path: str) -> tuple[str, ...]:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        return tuple(z.read(name).decode("utf-8").splitlines())


def model_label_map(cfg: LibraryConfig) -> list[str] | None:
    p = cfg.model_path("efficientdet_lite0")
    return list(_labels_from_model(str(p))) if p else None


def object_labels(cfg: LibraryConfig) -> set[str]:
    labels = model_label_map(cfg) or []
    return {l for l in labels if l and l != "???"}


def resolve_object_label(cfg: LibraryConfig, value: str) -> str | None:
    v = value.strip().lower().replace("_", " ")
    labels = object_labels(cfg)
    if v in labels:
        return v
    alias = OBJECT_ALIASES.get(v)
    if alias in labels:
        return alias
    if v.endswith("s") and v[:-1] in labels:
        return v[:-1]
    return None


THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "organize" / "decision_thresholds.json"


@lru_cache(maxsize=1)
def _thresholds() -> dict:
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8")) if THRESHOLDS_PATH.is_file() else {}


def decision_threshold(question_id: str, option: str | None = None, purpose: str = "collection") -> float:
    """Validation-selected threshold for a decision (dev split), else the catalog default.

    ``purpose`` is "collection" (high-trust smart sets) or "filter" (typed search filters).
    """
    t = _thresholds().get("thresholds", {})
    key = f"{purpose}:{question_id}" + (f"={option}" if option else "")
    if key in t:
        return float(t[key])
    return float(catalog()["collection_threshold" if purpose == "collection" else "filter_threshold"])


def thresholds_version() -> str | None:
    return _thresholds().get("version")
