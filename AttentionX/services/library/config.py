"""Validated configuration for the local media library.

All roots are separate managed directories: originals, derived blobs, models,
temp work and exports never share a directory. Feature flags come from the
environment (see ``docs/runbook.md``); cloud permissions are off by default
and an API key's presence never implies consent.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = APP_ROOT / "docs" / "model-manifest.json"


class ConfigError(ValueError):
    pass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if raw not in {"0", "1", "true", "false"}:
        raise ConfigError(f"{name} must be 0/1/true/false, got {raw!r}")
    return raw in {"1", "true"}


def _int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name)
    value = default if raw in (None, "") else int(raw)
    if not lo <= value <= hi:
        raise ConfigError(f"{name}={value} outside [{lo}, {hi}]")
    return value


@dataclass(frozen=True)
class Limits:
    max_image_bytes: int = 50 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_batch_files: int = 2000
    max_folder_depth: int = 8
    thumb_long_edge: int = 512
    ocr_tile_edge: int = 1280          # tile side at OCR resolution
    ocr_tile_overlap: int = 160
    ocr_max_tiles: int = 24
    ocr_max_seconds: float = 60.0
    ocr_min_readable_scale: float = 1.0  # never downscale screenshots below native for OCR
    region_views_max: int = 4
    job_max_attempts: int = 3
    job_lease_seconds: int = 300
    search_max_limit: int = 200


@dataclass(frozen=True)
class Features:
    ocr: bool = True
    ocr_fallback_tesseract: bool = True
    embeddings: bool = True
    ocr_text_embeddings: bool = True
    objects: bool = True
    context: bool = True
    clustering: bool = True
    asr: bool = False
    jev: bool = False
    onejev: bool = False
    local_only: bool = True
    allow_cloud_text: bool = False
    allow_cloud_frames: bool = False

    def validate(self) -> None:
        if self.local_only and (self.allow_cloud_text or self.allow_cloud_frames or self.jev):
            raise ConfigError(
                "ANALYSIS_LOCAL_ONLY=1 forbids cloud text/frames and the cloud Jev adapter"
            )


@dataclass(frozen=True)
class LibraryConfig:
    library_root: Path
    model_root: Path
    library_id: str = "local"
    ocr_languages: tuple[str, ...] = ("en",)
    limits: Limits = field(default_factory=Limits)
    features: Features = field(default_factory=Features)

    # Managed roots -------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.library_root / "library.sqlite3"

    @property
    def originals_root(self) -> Path:
        return self.library_root / "originals"

    @property
    def derived_root(self) -> Path:
        return self.library_root / "derived"

    @property
    def temp_root(self) -> Path:
        return self.library_root / "tmp"

    @property
    def exports_root(self) -> Path:
        return self.library_root / "exports"

    def ensure_dirs(self) -> None:
        for p in (self.library_root, self.originals_root, self.derived_root,
                  self.temp_root, self.exports_root):
            p.mkdir(parents=True, exist_ok=True)

    # Models --------------------------------------------------------------
    def model_dir(self, model: str) -> Path:
        return self.model_root / model

    def model_path(self, model: str, filename: str | None = None) -> Path | None:
        """Path of a provisioned model file, or None when not provisioned.

        A model counts as provisioned only after scripts/provision_models.py
        verified its hashes and wrote PROVISIONED.json.
        """
        d = self.model_dir(model)
        stamp = d / "PROVISIONED.json"
        if not stamp.is_file():
            return None
        if filename is None:
            files = json.loads(stamp.read_text(encoding="utf-8")).get("files", {})
            if len(files) != 1:
                return d
            filename = next(iter(files))
        p = d / filename
        return p if p.is_file() else None

    def with_overrides(self, **kwargs) -> "LibraryConfig":
        return replace(self, **kwargs)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def config_from_env(library_root: str | Path | None = None) -> LibraryConfig:
    features = Features(
        ocr=_flag("ANALYSIS_OCR", True),
        ocr_fallback_tesseract=_flag("ANALYSIS_OCR_TESSERACT_FALLBACK", True),
        embeddings=_flag("ANALYSIS_EMBEDDINGS", True),
        ocr_text_embeddings=_flag("ANALYSIS_OCR_TEXT_EMBEDDINGS", True),
        objects=_flag("ANALYSIS_OBJECTS", True),
        context=_flag("ANALYSIS_CONTEXT", True),
        clustering=_flag("ANALYSIS_CLUSTERING", True),
        asr=_flag("ANALYSIS_ASR", False),
        jev=_flag("ANALYSIS_JEV", False),
        onejev=_flag("ANALYSIS_ONEJEV", False),
        local_only=_flag("ANALYSIS_LOCAL_ONLY", True),
        allow_cloud_text=_flag("ANALYSIS_ALLOW_CLOUD_TEXT", False),
        allow_cloud_frames=_flag("ANALYSIS_ALLOW_CLOUD_FRAMES", False),
    )
    features.validate()
    langs = tuple(
        x.strip() for x in os.getenv("ANALYSIS_OCR_LANGUAGES", "en").split(",") if x.strip()
    )
    limits = Limits(
        max_image_bytes=_int("LIBRARY_MAX_IMAGE_MB", 50, 1, 1024) * 1024 * 1024,
        max_image_pixels=_int("LIBRARY_MAX_IMAGE_MEGAPIXELS", 40, 1, 400) * 1_000_000,
        ocr_max_tiles=_int("LIBRARY_OCR_MAX_TILES", 24, 1, 400),
    )
    root = Path(library_root or os.getenv("ATTENTIONX_LIBRARY_ROOT", APP_ROOT / "data" / "library"))
    model_root = Path(os.getenv("ATTENTIONX_MODEL_ROOT", APP_ROOT / "data" / "models"))
    return LibraryConfig(
        library_root=root.resolve(),
        model_root=model_root.resolve(),
        library_id=os.getenv("ATTENTIONX_LIBRARY_ID", "local"),
        ocr_languages=langs or ("en",),
        limits=limits,
        features=features,
    )


@lru_cache(maxsize=1)
def get_config() -> LibraryConfig:
    return config_from_env()
