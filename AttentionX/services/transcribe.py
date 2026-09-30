"""F03 — Speech Transcription

Spec reference: Features/F03-transcription/SPEC.md

ASR is optional. faster-whisper is imported lazily so the image library (and
this module) import without it, and models are cached per (size, device,
compute_type) inside the owning process instead of being rebuilt per run.
An empty transcript is a successful "no speech" result, not an error.
"""
from __future__ import annotations

import threading
from typing import Any

from models.schemas import TranscriptSegment, TranscriptionError

_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
_CACHE_LOCK = threading.Lock()


def asr_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def _get_model(model_size: str, device: str = "cpu", compute_type: str = "int8") -> Any:
    key = (model_size, device, compute_type)
    with _CACHE_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscriptionError(
                    "ASR unavailable: faster-whisper is not installed"
                ) from e
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            _MODEL_CACHE[key] = model
        return model


def transcribe(wav_path: str, model_size: str = "base") -> list[TranscriptSegment]:
    """Run faster-whisper on wav_path.

    Returns ordered list of TranscriptSegment (possibly empty when no speech is
    detected). Raises TranscriptionError if the model cannot load or decoding fails.
    """
    try:
        model = _get_model(model_size)
        segments_iter, _ = model.transcribe(wav_path, beam_size=5)
        return [
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
            for seg in segments_iter
            if seg.text.strip()
        ]
    except TranscriptionError:
        raise
    except Exception as e:
        raise TranscriptionError(f"transcription failed: {type(e).__name__}: {e}") from e
