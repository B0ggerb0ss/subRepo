from __future__ import annotations

from utils.time_utils import fmt_srt_time


def test_fmt_srt_time_formats_milliseconds() -> None:
    assert fmt_srt_time(1.234) == "00:00:01,234"


def test_fmt_srt_time_rounds_to_nearest_millisecond() -> None:
    assert fmt_srt_time(3661.9996) == "01:01:02,000"
