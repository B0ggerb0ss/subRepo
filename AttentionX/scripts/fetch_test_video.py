"""Fetch one test video from WenhaoWang/VideoUFO (HuggingFace dataset).

The dataset stores YouTube video IDs + clip timestamps; actual video files
are downloaded via yt-dlp.

Run from repo root:
    python scripts/fetch_test_video.py

Output:
    data/test/test_video.mp4        — downloaded clip
    data/test/test_video_meta.json  — VideoUFO metadata for the clip

Exit code 0 = video ready, 1 = failure (with fallback instructions).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUTPUT_VIDEO = Path("data/test/test_vido.mp4")
OUTPUT_META  = Path("data/test/test_video_meta.json")

TARGET_TOPICS = ["talk", "lecture", "interview", "explain", "discuss", "present", "demo"]
MAX_SCAN = 200


def _time_to_seconds(t: str) -> float:
    """Convert HH:MM:SS.mmm or HH:MM:SS string to seconds."""
    parts = t.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(parts[0])


def _topic_score(sample: dict) -> int:
    topic = str(sample.get("topic", "") or sample.get("Topic", "")).lower()
    caption = str(sample.get("detailed_caption", "") or sample.get("Detailed_Caption", "")).lower()
    text = topic + " " + caption
    return sum(1 for kw in TARGET_TOPICS if kw in text)


MIN_CLIP_DURATION = 20.0   # seconds — need enough for pipeline testing


def find_sample() -> dict:
    """Download first parquet shard from VideoUFO via huggingface_hub, scan for a good sample."""
    print("Fetching VideoUFO parquet shard (no full dataset download)...")
    from huggingface_hub import hf_hub_download
    import pandas as pd

    # Download only the first parquet shard (~few MB of metadata, no video files)
    parquet_path = hf_hub_download(
        repo_id="WenhaoWang/VideoUFO",
        filename="data/Full-00000-of-00093.parquet",
        repo_type="dataset",
    )
    df = pd.read_parquet(parquet_path)
    print(f"  Loaded {len(df)} entries from shard.")

    best_idx: int | None = None
    best_score = -1
    fallback_idx: int | None = None

    for i, row in df.head(MAX_SCAN).iterrows():
        d = row.to_dict()
        start_sec = _time_to_seconds(str(d.get("Start_Time", "0:00:00.000")))
        end_sec   = _time_to_seconds(str(d.get("End_Time",   "0:00:04.000")))
        duration  = end_sec - start_sec
        if duration < MIN_CLIP_DURATION:
            continue
        if fallback_idx is None:
            fallback_idx = i
        score = _topic_score(d)
        if score > best_score:
            best_score = score
            best_idx = i
            if score >= 1:
                break

    chosen_idx = best_idx if best_idx is not None else fallback_idx
    if chosen_idx is None:
        # No clip >= MIN_CLIP_DURATION found in MAX_SCAN entries; relax and take first entry
        chosen_idx = 0
    chosen = df.iloc[chosen_idx].to_dict()
    topic = chosen.get("Topic", "")
    print(f"  Selected row {chosen_idx}: topic={topic!r}, score={best_score}")
    return chosen


def download_video(sample: dict) -> bool:
    # ID format is "{youtube_video_id}.{clip_number}" — split to get the YT ID
    raw_id    = sample.get("ID") or sample.get("id") or sample.get("videoid") or ""
    video_id  = raw_id.rsplit(".", 1)[0] if "." in str(raw_id) else str(raw_id)
    start_raw = sample.get("Start_Time") or sample.get("start_time") or "0:00:00.000"
    end_raw   = sample.get("End_Time")   or sample.get("end_time")   or "0:00:30.000"

    if not video_id:
        print("ERROR: could not find video ID field in dataset sample.", file=sys.stderr)
        print(f"  Available keys: {list(sample.keys())}", file=sys.stderr)
        return False

    start_sec = _time_to_seconds(str(start_raw))
    end_sec   = _time_to_seconds(str(end_raw))
    duration  = end_sec - start_sec

    print(f"  video_id={video_id}, start={start_sec:.1f}s, end={end_sec:.1f}s, clip={duration:.1f}s")

    OUTPUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)

    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "--download-sections", f"*{start_sec}-{end_sec}",
        "--merge-output-format", "mp4",
        "--force-keyframes-at-cuts",
        "-o", str(OUTPUT_VIDEO),
        "--no-playlist",
        url,
    ]
    print(f"Downloading: {url}")
    try:
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            print(f"yt-dlp exited with code {result.returncode}", file=sys.stderr)
            return False
    except FileNotFoundError:
        print("ERROR: yt-dlp not found on PATH.", file=sys.stderr)
        return False

    if not OUTPUT_VIDEO.exists() or OUTPUT_VIDEO.stat().st_size == 0:
        print("ERROR: output file missing or empty after download.", file=sys.stderr)
        return False

    # Verify with ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(OUTPUT_VIDEO)],
        capture_output=True, text=True,
    )
    detected_dur = probe.stdout.strip()
    size_mb = OUTPUT_VIDEO.stat().st_size / (1024 * 1024)
    print(f"  Output: {OUTPUT_VIDEO} ({size_mb:.1f} MB, duration={detected_dur}s)")

    # Write metadata
    meta = {
        "video_id":   video_id,
        "topic":      sample.get("topic") or sample.get("Topic", ""),
        "caption":    sample.get("detailed_caption") or sample.get("Detailed_Caption", ""),
        "start_time": str(start_raw),
        "end_time":   str(end_raw),
        "local_path": str(OUTPUT_VIDEO.resolve()),
    }
    OUTPUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  Metadata: {OUTPUT_META}")
    return True


def print_fallback():
    print("\nFallback: manually place any MP4 at:", file=sys.stderr)
    print(f"  {OUTPUT_VIDEO.resolve()}", file=sys.stderr)
    print("Then run: python scripts/gate2_test.py data/test/test_video.mp4", file=sys.stderr)


def main() -> int:
    if OUTPUT_VIDEO.exists() and OUTPUT_VIDEO.stat().st_size > 0:
        size_mb = OUTPUT_VIDEO.stat().st_size / (1024 * 1024)
        print(f"Test video already exists: {OUTPUT_VIDEO} ({size_mb:.1f} MB)")
        print("Delete it and re-run to refresh.")
        return 0

    try:
        sample = find_sample()
    except Exception as e:
        print(f"ERROR scanning VideoUFO dataset: {e}", file=sys.stderr)
        print_fallback()
        return 1

    success = download_video(sample)
    if not success:
        print_fallback()
        return 1

    print(f"\nTEST VIDEO READY: {OUTPUT_VIDEO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
