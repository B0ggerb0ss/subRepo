"""Gate 3 — Transcription contract test."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import REPO_ROOT, check, summarize
from tests.support.media_factory import write_pattern_wav

import services.transcribe as transcribe_module
from services.transcribe import transcribe


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeWhisperModel:
    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, wav_path: str, beam_size: int = 5):
        segments = [
            _FakeSegment(0.0, 1.8, "Here is the first phrase."),
            _FakeSegment(1.8, 3.5, "You need a second phrase."),
            _FakeSegment(3.5, 5.4, "This is the final sample."),
        ]
        return iter(segments), {"beam_size": beam_size, "path": wav_path}


def main() -> int:
    print("\n=== Gate 3 — Transcription ===")
    print("Mode: offline contract check using a deterministic WhisperModel stub.\n")

    original = transcribe_module.WhisperModel
    with tempfile.TemporaryDirectory(prefix="attentionx_gate3_") as tmp:
        wav_path = write_pattern_wav(Path(tmp) / "speech.wav", duration=5.5)
        transcribe_module.WhisperModel = _FakeWhisperModel
        try:
            segments = transcribe(str(wav_path), model_size="base")
        finally:
            transcribe_module.WhisperModel = original

    results = [
        check("non-empty segment list returned", lambda: len(segments) > 0 or (_ for _ in ()).throw(RuntimeError("no segments"))),
        check(
            "start < end for every segment",
            lambda: all(seg.start < seg.end for seg in segments) or (_ for _ in ()).throw(RuntimeError("found non-positive span")),
        ),
        check(
            "timestamps are monotonically increasing",
            lambda: all(
                earlier.end <= later.start
                for earlier, later in zip(segments, segments[1:])
            ) or (_ for _ in ()).throw(RuntimeError("timestamps not monotonic")),
        ),
        check(
            "sample phrases available for manual comparison",
            lambda: ", ".join(seg.text for seg in segments),
        ),
    ]
    return summarize(3, results)


if __name__ == "__main__":
    sys.exit(main())
