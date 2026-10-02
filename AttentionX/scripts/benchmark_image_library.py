#!/usr/bin/env python3
"""Latency / memory / index-size benchmark for the image library.

Parts (each clearly labelled in the output):
  analysis   real images, one warm worker in this process: per-stage latency,
             model load (cold) time, peak RSS (VmHWM)
  submit     import_files() of one image -> returns job id (UI submission path)
  reopen     active_metadata() reads (no hashing, no inference)
  scale      SEARCH-ONLY benchmark at ~N assets built by replicating the eval
             library's analyzed rows with new ids and perturbed vectors
             (synthetic scale rows: measures index/search cost, not accuracy)
  incremental  one new real image into the scaled library: analyze + organize,
             versus a full organization rebuild

Usage: python scripts/benchmark_image_library.py [--scale 10000] [--images 30]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def rss_mb() -> dict:
    out = {}
    for line in open("/proc/self/status"):
        if line.startswith(("VmRSS", "VmHWM")):
            k, v = line.split(":")
            out[k] = round(int(v.split()[0]) / 1024, 1)
    return out


def pct(v, q):
    return round(float(np.percentile(v, q)), 2) if v else None


def bench_analysis(n_images: int, work: Path) -> dict:
    from services.analyze.providers import get_providers
    from services.library.config import config_from_env
    from services.library.registry import Library
    from services.library.worker import Worker

    labels = [json.loads(l) for l in (ROOT / "data/eval_set/labels.jsonl").read_text().splitlines()]
    rnd = random.Random(3)
    pick = rnd.sample([r for r in labels if not r["category"].endswith("variant")], n_images)
    cfg = config_from_env(work / "bench_lib")
    lib = Library(cfg)
    before = rss_mb()
    t = time.perf_counter()
    prov = get_providers(cfg)
    loads = {}
    for name, fn in (("ocr", prov.ocr_engine), ("clip", prov.clip), ("minilm", prov.text_encoder),
                     ("objects", prov.detector)):
        t0 = time.perf_counter()
        fn()
        loads[name] = round(time.perf_counter() - t0, 2)
    # CLIP's visual session is created lazily on first image encode; include it.
    t0 = time.perf_counter()
    import numpy as _np

    prov.clip().encode_images([_np.zeros((32, 32, 3), _np.uint8)])
    loads["clip_visual"] = round(time.perf_counter() - t0, 2)
    paths = [ROOT / "data/eval_set" / r["file"] for r in pick]
    t_imp = time.perf_counter()
    batch = lib.import_files(paths)
    t_imp = time.perf_counter() - t_imp
    t_an = time.perf_counter()
    Worker(cfg, lib.repo).run_until_idle()
    t_an = time.perf_counter() - t_an
    rows = lib.repo.query("SELECT stage, finished_at-started_at d FROM job_stages WHERE started_at IS NOT NULL AND"
                          " finished_at IS NOT NULL")
    by = {}
    for r in rows:
        by.setdefault(r["stage"], []).append(r["d"])
    per_image = []
    for jid in batch.job_ids:
        st = lib.repo.query("SELECT MIN(started_at) a, MAX(finished_at) b FROM job_stages WHERE job_id=?", (jid,))[0]
        per_image.append(st["b"] - st["a"])
    basic = []
    for jid in batch.job_ids:
        r = lib.repo.query_one("SELECT SUM(finished_at-started_at) s FROM job_stages WHERE job_id=? AND stage IN"
                               " ('pixels','ocr')", (jid,))
        basic.append(r["s"])
    mp = [ (r["width"] or 0) * (r["height"] or 0) / 1e6 for r in lib.repo.query("SELECT width, height FROM assets")]
    after = rss_mb()
    out = {"images": n_images, "model_load_s": loads, "import_copy_hash_s_total": round(t_imp, 3),
           "analyze_wall_s": round(t_an, 2), "per_image_total_s": {"p50": pct(per_image, 50), "p95": pct(per_image, 95)},
           "basic_profile_pixels_plus_ocr_s": {"p50": pct(basic, 50), "p95": pct(basic, 95)},
           "megapixels": {"p50": pct(mp, 50), "max": round(max(mp), 2)},
           "stage_s": {k: {"p50": pct(v, 50), "p95": pct(v, 95)} for k, v in sorted(by.items())},
           "rss_mb_before_models": before, "rss_mb_after": after}
    # Submission latency (UI path): one import returns a job id without analysis.
    sub = []
    for i in range(20):
        p = work / f"submit_{i}.png"
        from PIL import Image

        Image.new("RGB", (800, 600), (i * 10 % 255, 40, 90)).save(p)
        t0 = time.perf_counter()
        lib.import_files([p])
        sub.append((time.perf_counter() - t0) * 1000)
    out["submit_ms"] = {"p50": pct(sub, 50), "p95": pct(sub, 95), "note": "copy+hash+register+enqueue, 800x600 PNG"}
    from services.library.metadata import active_metadata

    ids = [r["id"] for r in lib.repo.query("SELECT id FROM assets WHERE metadata_revision>0")]
    ro = []
    for _ in range(5):
        for a in ids:
            t0 = time.perf_counter()
            active_metadata(lib.repo, a)
            ro.append((time.perf_counter() - t0) * 1000)
    out["metadata_reopen_ms"] = {"p50": pct(ro, 50), "p95": pct(ro, 95), "n": len(ro)}
    lib.close()
    return out


def bench_2mp(work: Path, n: int = 10) -> dict:
    """Basic profile (pixels + OCR) and full analysis on ~2 MP (1920x1080) images:
    half text-heavy renders, half upscaled real photos."""
    from PIL import Image, ImageDraw, ImageFont

    from services.library.config import config_from_env
    from services.library.registry import Library
    from services.library.worker import Worker

    src = work / "2mp"
    src.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    for i in range(n // 2):
        im = Image.new("RGB", (1920, 1080), "white")
        d = ImageDraw.Draw(im)
        for row in range(26):
            d.text((60, 30 + row * 40), f"Row {row} of report {i}: quarterly metrics, latency p95 and error budget", fill="black", font=font)
        im.save(src / f"text_{i}.png")
    photos = sorted((ROOT / "data/eval_sources/flower_photos/tulips").glob("*.jpg"))[: n - n // 2]
    for i, p in enumerate(photos):
        Image.open(p).convert("RGB").resize((1920, 1080), Image.BICUBIC).save(src / f"photo_{i}.jpg", quality=90)
    lib = Library(config_from_env(work / "lib2mp"))
    b = lib.import_files(sorted(src.iterdir()))
    t = time.perf_counter()
    Worker(lib.cfg, lib.repo).run_until_idle()
    wall = time.perf_counter() - t
    basic, total = [], []
    for jid in b.job_ids:
        r = lib.repo.query_one("SELECT SUM(finished_at-started_at) s FROM job_stages WHERE job_id=? AND stage IN"
                               " ('pixels','ocr')", (jid,))
        basic.append(r["s"])
        r = lib.repo.query_one("SELECT MAX(finished_at)-MIN(started_at) s FROM job_stages WHERE job_id=?", (jid,))
        total.append(r["s"])
    lib.close()
    return {"images": n, "megapixels": 2.07, "basic_pixels_plus_ocr_s": {"p50": pct(basic, 50), "p95": pct(basic, 95)},
            "full_analysis_s": {"p50": pct(total, 50), "p95": pct(total, 95)}, "wall_s": round(wall, 2),
            "note": "warm providers (loaded by the earlier analysis benchmark in this process)"}


def build_scaled(src_db: Path, dst_root: Path, target: int) -> Path:
    """Replicate analyzed rows of the eval library into a ~target-asset library."""
    from services.library.config import config_from_env
    from services.library.registry import Library

    dst_root.mkdir(parents=True, exist_ok=True)
    lib = Library(config_from_env(dst_root))  # creates schema + namespaces
    lib.close()
    dst = sqlite3.connect(dst_root / "library.sqlite3")
    dst.execute("ATTACH DATABASE ? AS src", (str(src_db),))
    src_assets = [r[0] for r in dst.execute("SELECT id FROM src.assets WHERE deleted_at IS NULL AND metadata_revision>0")]
    reps = max(1, target // len(src_assets))
    rng = np.random.default_rng(0)
    dst.execute("BEGIN")
    for k in range(reps):
        suf = f"_x{k:03d}"
        dst.execute(f"""INSERT INTO assets (id, library_id, content_hash, kind, mime, byte_size, width, height,
                        original_ref, thumb_ref, created_at, deleted_at, metadata_revision, analysis_generation,
                        phash64, dhash64)
                        SELECT id||'{suf}', library_id, content_hash||'{suf}', kind, mime, byte_size,
                        width, height, original_ref, thumb_ref, created_at+{k}, NULL, metadata_revision, 0,
                        phash64, dhash64
                        FROM src.assets WHERE deleted_at IS NULL AND metadata_revision>0""")
        dst.execute(f"""INSERT INTO metadata_revisions SELECT m.asset_id||'{suf}', m.revision, m.schema_version, m.payload,
                        NULL, m.created_at FROM src.metadata_revisions m JOIN src.assets a ON a.id=m.asset_id AND
                        a.metadata_revision=m.revision""")
        for t in ("ocr_regions", "object_observations", "decisions"):
            src_cols = {r[1] for r in dst.execute(f"PRAGMA src.table_info({t})")}
            cols = [r[1] for r in dst.execute(f"PRAGMA main.table_info({t})") if r[1] in src_cols]
            sel = ",".join(f"asset_id||'{suf}'" if c == "asset_id" else c for c in cols)
            dst.execute(f"INSERT INTO {t} ({','.join(cols)}) SELECT {sel} FROM src.{t}")
        dst.execute(f"INSERT INTO ocr_docs SELECT asset_id||'{suf}', revision, norm_text FROM src.ocr_docs")
        dst.execute(f"INSERT INTO ocr_doc_words(norm_text, asset_id) SELECT replace(norm_text, char(10), ' '),"
                    f" asset_id||'{suf}' FROM src.ocr_docs")
        dst.execute(f"INSERT INTO ocr_doc_tri(norm_text, asset_id) SELECT replace(norm_text, char(10), ' '),"
                    f" asset_id||'{suf}' FROM src.ocr_docs")
        rows = dst.execute("SELECT namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
                           " metadata_revision FROM src.vectors").fetchall()
        batch = []
        for ns, aid, view, kind, region, refs, vec, rev in rows:
            v = np.frombuffer(vec, dtype=np.float32)
            v = v + rng.normal(0, 0.01, v.shape).astype(np.float32) if k else v
            v = (v / np.linalg.norm(v)).astype(np.float32)
            batch.append((ns, aid + suf, view, kind, region, refs, v.tobytes(), rev))
        dst.executemany("INSERT INTO vectors(namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
                        " metadata_revision) VALUES (?,?,?,?,?,?,?,?)", batch)
    dst.execute("INSERT OR REPLACE INTO vector_namespaces SELECT * FROM src.vector_namespaces")
    dst.execute("UPDATE vector_namespaces SET revision = revision + 1")
    dst.execute("INSERT OR IGNORE INTO libraries SELECT * FROM src.libraries")
    dst.execute("COMMIT")
    dst.execute("DETACH DATABASE src")
    dst.close()
    return dst_root


def bench_search(root: Path) -> dict:
    from services.library.config import config_from_env
    from services.library.registry import Library

    lib = Library(config_from_env(root))
    n = lib.count_assets()
    nvec = lib.repo.query_one("SELECT COUNT(*) n FROM vectors")["n"]
    db_mb = round((root / "library.sqlite3").stat().st_size / 1e6, 1)
    lex_q = ['text:"feature store"', 'text:"kubernetes"', 'text:"hiring"', "capture:screenshot", "source:linkedin",
             'text:"c#"', "object:person", "context:source_code"]
    hyb_q = ["posts discussing train-serving skew", "a field of sunflowers", "LinkedIn ML jobs mentioning Python",
             "kubernetes deployment problems", "red roses", "chat about a failed deploy"]
    before = rss_mb()
    t0 = time.perf_counter()
    lib.search("warm up the encoders and matrices")
    cold_first = time.perf_counter() - t0
    after_load = rss_mb()
    res = {}
    for name, qs, ch in (("lexical_filter", lex_q, ["lexical"]), ("hybrid", hyb_q, None)):
        lat = []
        for _ in range(5):
            for q in qs:
                lib.search_service._cache.clear()
                t = time.perf_counter()
                lib.search(q, limit=40, channels=ch)
                lat.append((time.perf_counter() - t) * 1000)
        res[name] = {"p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "n": len(lat)}
    lat = []
    for q in hyb_q * 3:
        t = time.perf_counter()
        lib.search(q, limit=40)
        lat.append((time.perf_counter() - t) * 1000)
    res["hybrid_cached_result"] = {"p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95)}
    out = {"assets": n, "vectors": nvec, "db_mb": db_mb, "first_query_incl_model_and_matrix_load_s": round(cold_first, 2),
           "rss_mb_before_first_query": before, "rss_mb_after_matrices": after_load, "latency": res}
    lib.close()
    return out


def bench_incremental(root: Path, image: Path) -> dict:
    from services.library.config import config_from_env
    from services.library.registry import Library
    from services.library.worker import Worker
    from services.organize.service import refresh_all

    lib = Library(config_from_env(root))
    batch = lib.import_files([image])
    t = time.perf_counter()
    Worker(lib.cfg, lib.repo).run_until_idle()
    t_one = time.perf_counter() - t
    org = lib.repo.query_one("SELECT finished_at-started_at d FROM job_stages WHERE job_id=? AND stage='organize'",
                             (batch.job_ids[0],))
    t = time.perf_counter()
    refresh_all(lib.repo, lib.cfg)
    t_full = time.perf_counter() - t
    lib.close()
    return {"one_new_image_analyze_and_organize_s": round(t_one, 2), "incremental_organize_stage_s": round(org["d"], 3),
            "full_organization_rebuild_s": round(t_full, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=10000)
    ap.add_argument("--images", type=int, default=30)
    ap.add_argument("--src-lib", type=Path, default=ROOT / "data/eval_runs/lib")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("--skip-analysis", action="store_true")
    args = ap.parse_args()
    from scripts.eval_image_library import hardware

    work = Path(tempfile.mkdtemp(prefix="ax-bench-"))
    report = {"hardware": hardware(), "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        if not args.skip_analysis:
            report["analysis"] = bench_analysis(args.images, work)
            report["analysis_2mp"] = bench_2mp(work)
        scaled = build_scaled(args.src_lib / "library.sqlite3", work / "scaled", args.scale)
        report["scale_search"] = bench_search(scaled)
        report["scale_search"]["note"] = ("synthetic scale rows: eval-library analyses replicated with new ids and "
                                          "perturbed vectors; measures search/index cost only")
        img = next(p for p in sorted((ROOT / "tests/fixtures/images").glob("*.png")) if "li_" in p.name)
        report["incremental"] = bench_incremental(scaled, img)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "benchmark.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
