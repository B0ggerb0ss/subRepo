#!/usr/bin/env python3
"""Measure the M8 video path: admission, keyframe sampling, per-keyframe analysis, search, disk, and
Generate's normalized-proxy reuse. Writes reports/benchmark_video.json.

Inputs are rendered with FFmpeg (a new on-screen text line every ``--slide`` seconds over a moving test
pattern). They exercise the real pipeline at known sizes; they are *not* representative footage.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def render(path: Path, seconds: int, slide: int, size=(1280, 720)) -> list[tuple[str, float]]:
    w, h = size
    texts = []
    filters = []
    for i in range(0, seconds, slide):
        t = f"slide {i // slide:03d} release checklist item {i // slide * 7 % 101}"
        texts.append((t, float(i)))
        filters.append(f"drawtext=fontfile={FONT}:text='{t}':fontsize=40:fontcolor=white:box=1:boxcolor=black@0.6:"
                       f"x=80:y={h - 140}:enable='between(t,{i},{i + slide})'")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=25:d={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=22050:duration={seconds}",
           "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return texts


def du(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--durations", default="60,300")
    ap.add_argument("--slide", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "benchmark_video.json")
    args = ap.parse_args()

    from services.library.config import config_from_env
    from services.library.registry import Library
    from services.library.worker import Worker

    base = Path(tempfile.mkdtemp(prefix="ax-vbench-"))
    lib = Library(config_from_env(base / "lib"))
    worker = Worker(lib.cfg, lib.repo)
    results = []
    for secs in (int(x) for x in args.durations.split(",")):
        src = base / f"talk_{secs}s.mp4"
        texts = render(src, secs, args.slide)
        t0 = time.perf_counter()
        batch = lib.import_files([src])
        admit = time.perf_counter() - t0
        t0 = time.perf_counter()
        status = worker.run_until_idle()
        wall = time.perf_counter() - t0
        aid = batch.asset_ids[0]
        job = lib.queue.get(batch.job_ids[0])
        stages = {s.stage: round((s.finished_at or 0) - (s.started_at or 0), 3) for s in job.stages
                  if s.started_at and s.finished_at}
        meta = lib.asset_detail(aid)["metadata"]
        kf = meta["video"]["keyframes"]
        # Timed literal recall over every rendered line, and search latency.
        found, lat, terr = 0, [], []
        for text, t in texts:
            lib.search_service._cache.clear()
            q0 = time.perf_counter()
            r = lib.search(f'text:"{text}"')
            lat.append((time.perf_counter() - q0) * 1000)
            ev = [e for h in r.hits for e in h.reasons if e.reason == "OCR_PHRASE" and e.t_s is not None]
            if ev:
                found += 1
                terr.append(abs(ev[0].t_s - t))
        kdir = base / "lib" / Path(kf[0]["frame_ref"]).parent
        results.append({
            "duration_s": secs, "size": "1280x720", "bytes": src.stat().st_size, "status": status,
            "admission_ms": round(admit * 1000, 1), "analysis_wall_s": round(wall, 2),
            "analysis_x_realtime": round(wall / secs, 3), "stage_s": stages,
            "keyframes": len(kf), "keyframe_disk_kb": round(du(kdir) / 1024, 1),
            "rendered_text_lines": len(texts), "literal_found": found,
            "literal_recall": round(found / len(texts), 3),
            "timestamp_abs_err_s_max": round(max(terr), 2) if terr else None,
            "search_ms": {"p50": round(statistics.median(lat), 1),
                          "p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1)},
        })
        print(json.dumps(results[-1]), flush=True)

    # Generate: first run normalizes, second reuses the cached proxy.
    import app

    gen = {}
    aid = results and lib.search("type:video").hits[-1].asset_id
    quiet = lambda *a, **k: None  # noqa: E731
    for run in ("cold", "warm"):
        t0 = time.perf_counter()
        out = app.generate_from_library(lib, aid, None, progress=quiet)
        gen[run] = {"s": round(time.perf_counter() - t0, 2), "clips": len(out[3]), "status": out[4][:200]}
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "machine": {"cpus": __import__("os").cpu_count(), "python": platform.python_version()},
              "note": "FFmpeg-rendered testsrc2 + drawtext inputs; plumbing/cost measurement, not footage quality",
              "videos": results, "generate_from_library": gen}
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(gen, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
