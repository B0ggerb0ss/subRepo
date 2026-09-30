"""F03 — Speech Transcription

Spec reference: Features/F03-transcription/SPEC.md
"""
from __future__ import annotations

from faster_whisper import WhisperModel

from models.schemas import TranscriptSegment, TranscriptionError


def transcribe(wav_path: str, model_size: str = "base") -> list[TranscriptSegment]:
    """Run faster-whisper on wav_path.

    Returns ordered list of TranscriptSegment.
    Raises TranscriptionError if transcription fails or produces no output.
    """
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments_iter, _ = model.transcribe(wav_path, beam_size=5)
        results = [
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
            for seg in segments_iter
        ]
    except Exception as e:
        raise TranscriptionError(f"transcription failed: {e}") from e

    if not results:
        raise TranscriptionError("no speech detected in audio")

    return results
