#!/usr/bin/env python3
"""Import data/eval_set into a dedicated library and analyze it with N workers.

Usage: python scripts/build_eval_library.py [--lib data/eval_runs/lib] [--workers 2]
Timing and per-stage durations are persisted in the library's job tables and
read by scripts/eval_image_library.py and scripts/benchmark_image_library.py.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _work(lib_root: str, threads: int) -> None:
    os.environ["ATTENTIONX_ORT_THREADS"] = str(threads)
    from services.library.config import config_from_env
    from services.library.worker import Worker

    Worker(config_from_env(lib_root)).run_until_idle()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=str(ROOT / "data" / "eval_runs" / "lib"))
    ap.add_argument("--eval-set", default=str(ROOT / "data" / "eval_set"))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--reanalyze", action="store_true",
                    help="re-run analysis for every asset (unchanged stages come from cache)")
    args = ap.parse_args()

    from services.library.config import config_from_env
    from services.library.registry import Library

    if args.reanalyze:
        lib = Library(config_from_env(args.lib))
        jobs = [lib.retry_asset(r["id"]) for r in lib.repo.query("SELECT id FROM assets WHERE deleted_at IS NULL")]
        lib.close()
        t1 = time.time()
        ctx = mp.get_context("spawn")
        procs = [ctx.Process(target=_work, args=(args.lib, args.threads)) for _ in range(args.workers)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        wall = time.time() - t1
        lib = Library(config_from_env(args.lib))
        lib.refresh_organization(inline=True)
        rows = lib.repo.query(
            f"SELECT stage, status, COUNT(*) n FROM job_stages WHERE job_id IN ({','.join('?' * len(jobs))})"
            " GROUP BY stage, status ORDER BY stage", tuple(jobs))
        summary = {"reanalyze_wall_s": round(wall, 1), "jobs": len(jobs),
                   "stage_status": [dict(r) for r in rows]}
        Path(args.lib, "reanalyze_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        lib.close()
        return 0

    labels = [json.loads(l) for l in Path(args.eval_set, "labels.jsonl").read_text().splitlines() if l.strip()]
    lib = Library(config_from_env(args.lib))
    t0 = time.time()
    paths = [Path(args.eval_set) / r["file"] for r in labels]
    batch = lib.import_files(paths, display_names={str(p): p.name for p in paths}, source_note="eval_set")
    t_import = time.time() - t0
    mapping = {r["id"]: aid for r, aid in zip(labels, batch.asset_ids)} if batch.rejected == 0 else None
    if mapping is None:
        print(json.dumps([r.model_dump() for r in batch.rejections], indent=2))
        return 1
    Path(args.lib, "eval_mapping.json").write_text(json.dumps(mapping, indent=1))
    lib.close()

    t1 = time.time()
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_work, args=(args.lib, args.threads)) for _ in range(args.workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    t_analyze = time.time() - t1

    lib = Library(config_from_env(args.lib))
    t2 = time.time()
    lib.refresh_organization(inline=True)
    t_org = time.time() - t2
    summary = {"images": len(labels), "import_s": round(t_import, 2), "analyze_wall_s": round(t_analyze, 1),
               "workers": args.workers, "ort_threads": args.threads, "organize_full_s": round(t_org, 2),
               "jobs": lib.job_summary()}
    Path(args.lib, "build_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    lib.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
