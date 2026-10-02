"""Per-process provider registry: lazily constructed, then kept warm.

Heavy objects (ONNX sessions, TFLite interpreters) are created once in the
process that runs analysis (the worker) and reused. The UI process only loads
the CLIP text encoder / MiniLM for query encoding, on first search.

``availability()`` answers "could this provider run?" without loading weights,
so the UI can show honest capability badges cheaply.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from services.library.config import LibraryConfig, load_manifest


class ProviderUnavailable(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Availability:
    name: str
    enabled: bool
    available: bool
    code: str            # ok | disabled | missing | error
    detail: str


class Providers:
    def __init__(self, cfg: LibraryConfig) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._cache: dict[str, object] = {}
        self._errors: dict[str, ProviderUnavailable] = {}

    def _get(self, key: str, factory):
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if key in self._errors:
                raise self._errors[key]
            try:
                obj = factory()
            except ProviderUnavailable as e:
                self._errors[key] = e
                raise
            self._cache[key] = obj
            return obj

    def reset_errors(self) -> None:
        with self._lock:
            self._errors.clear()

    # -- OCR -------------------------------------------------------------
    def ocr_engine(self):
        from services.analyze.ocr import OCRUnavailable, build_engine

        f = self.cfg.features
        if not f.ocr:
            raise ProviderUnavailable("disabled", "OCR disabled by ANALYSIS_OCR=0")

        def make():
            try:
                expected = load_manifest()["bundled"]["rapidocr_onnxruntime"]["models"]
                engine, note = build_engine(self.cfg.ocr_languages, f.ocr_fallback_tesseract, expected)
                engine.fallback_note = note
                return engine
            except OCRUnavailable as e:
                raise ProviderUnavailable(e.code, str(e)) from e

        return self._get("ocr", make)

    # -- Embeddings --------------------------------------------------------
    def clip(self):
        if not self.cfg.features.embeddings:
            raise ProviderUnavailable("disabled", "image-text embeddings disabled by ANALYSIS_EMBEDDINGS=0")

        def make():
            from services.analyze.embeddings import ClipProvider

            return ClipProvider.load(self.cfg)

        return self._get("clip", make)

    def text_encoder(self):
        if not self.cfg.features.ocr_text_embeddings:
            raise ProviderUnavailable("disabled", "OCR-text embeddings disabled by ANALYSIS_OCR_TEXT_EMBEDDINGS=0")

        def make():
            from services.analyze.embeddings import MiniLMProvider

            return MiniLMProvider.load(self.cfg)

        return self._get("minilm", make)

    # -- Objects ----------------------------------------------------------
    def detector(self):
        if not self.cfg.features.objects:
            raise ProviderUnavailable("disabled", "object detection disabled by ANALYSIS_OBJECTS=0")

        def make():
            from services.analyze.objects import ObjectDetector

            return ObjectDetector.load(self.cfg)

        return self._get("objects", make)

    # -- Availability (no weights loaded) ---------------------------------
    def availability(self) -> list[Availability]:
        f = self.cfg.features
        out = []

        def model_state(name: str) -> tuple[bool, str]:
            ok = self.cfg.model_path(name) is not None
            return ok, "provisioned" if ok else f"model '{name}' not provisioned (scripts/provision_models.py)"

        # OCR: check importability + bundled files without constructing sessions.
        try:
            import importlib.util

            has_rapid = importlib.util.find_spec("rapidocr_onnxruntime") is not None
        except Exception:
            has_rapid = False
        import shutil as _sh

        has_tess = _sh.which("tesseract") is not None
        if not f.ocr:
            out.append(Availability("ocr", False, False, "disabled", "ANALYSIS_OCR=0"))
        elif has_rapid:
            out.append(Availability("ocr", True, True, "ok", "rapidocr_onnxruntime (PP-OCRv4)"))
        elif has_tess and f.ocr_fallback_tesseract:
            out.append(Availability("ocr", True, True, "ok", "tesseract fallback only"))
        else:
            out.append(Availability("ocr", True, False, "missing", "no OCR engine installed"))

        for name, flag, model in (
            ("embeddings", f.embeddings, "clip_vit_b32_laion2b_s34b_b79k"),
            ("ocr_text_embeddings", f.ocr_text_embeddings, "minilm_l6_v2"),
            ("objects", f.objects, "efficientdet_lite0"),
        ):
            if not flag:
                out.append(Availability(name, False, False, "disabled", "disabled by flag"))
            else:
                ok, detail = model_state(model)
                out.append(Availability(name, True, ok, "ok" if ok else "missing", detail))
        clip_ok = self.cfg.model_path("clip_vit_b32_laion2b_s34b_b79k") is not None
        if not f.context:
            out.append(Availability("context", False, False, "disabled", "ANALYSIS_CONTEXT=0"))
        else:
            out.append(Availability(
                "context", True, clip_ok and f.embeddings, "ok" if clip_ok and f.embeddings else "missing",
                "CLIP zero-shot decision backend + OCR/pixel evidence gates (uncalibrated)"
                if clip_ok else "needs the CLIP model"))
        out.append(Availability("clustering", f.clustering, f.clustering, "ok" if f.clustering else "disabled",
                                "sparse mutual-kNN over CLIP vectors"))
        out.append(Availability("onejev", f.onejev, False, "missing" if f.onejev else "disabled",
                                "OneJev not provisionable in this environment"))
        out.append(Availability("asr", f.asr, False, "missing" if f.asr else "disabled",
                                "Whisper weights not provisioned"))
        return out


_REGISTRY: dict[str, Providers] = {}
_REG_LOCK = threading.Lock()


def get_providers(cfg: LibraryConfig) -> Providers:
    key = f"{cfg.library_root}|{cfg.model_root}|{cfg.features}|{cfg.ocr_languages}"
    with _REG_LOCK:
        if key not in _REGISTRY:
            _REGISTRY[key] = Providers(cfg)
        return _REGISTRY[key]
