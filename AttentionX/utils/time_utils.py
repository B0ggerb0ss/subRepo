from __future__ import annotations


def fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp string: HH:MM:SS,mmm.

    SRT spec requires comma as millisecond separator, not period.
    """
    ms = int(round(seconds * 1000))
    h, ms  = divmod(ms, 3_600_000)
    m, ms  = divmod(ms,    60_000)
    s, ms  = divmod(ms,     1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
