#!/usr/bin/env python3
"""Command-line entry point for the image library (same services as the UI).

  python scripts/library_cli.py import FILE...          python scripts/library_cli.py import-folder DIR
  python scripts/library_cli.py analyze                 python scripts/library_cli.py status
  python scripts/library_cli.py search QUERY [--limit N] [--json]
  python scripts/library_cli.py similar ASSET_ID [--crop x0,y0,x1,y1]
  python scripts/library_cli.py collections             python scripts/library_cli.py refresh
  python scripts/library_cli.py export [--collection KEY] [--v1] [--filenames]
  python scripts/library_cli.py retry-failed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _print_hits(resp, as_json: bool) -> None:
    if as_json:
        print(resp.model_dump_json(indent=2))
        return
    for d in resp.degraded:
        print(f"! {d}")
    print(f"{resp.total_candidates} result(s), channels={resp.channels_used}, {resp.elapsed_ms:.0f} ms")
    for i, h in enumerate(resp.hits, 1):
        reasons = "; ".join(f"{e.reason}: {e.detail}" + (f" [{e.excerpt[:80]}]" if e.excerpt else "")
                            for e in h.reasons[:3])
        dup = f" (+{h.duplicate_count} near-dup)" if h.duplicate_count else ""
        print(f"{i:3d}. {h.asset_id}{dup}  {reasons}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", help="library root (default: ATTENTIONX_LIBRARY_ROOT or data/library)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("import-folder")
    p.add_argument("folder")
    sub.add_parser("analyze")
    sub.add_parser("status")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.add_argument("--expand-duplicates", action="store_true")
    p = sub.add_parser("similar")
    p.add_argument("asset_id")
    p.add_argument("--crop")
    p.add_argument("--json", action="store_true")
    sub.add_parser("collections")
    sub.add_parser("refresh")
    sub.add_parser("retry-failed")
    p = sub.add_parser("export")
    p.add_argument("--collection")
    p.add_argument("--v1", action="store_true")
    p.add_argument("--filenames", action="store_true")
    args = ap.parse_args()

    from services.library.config import config_from_env
    from services.library.registry import Library
    from services.library.worker import Worker
    from services.search.service import SearchError

    lib = Library(config_from_env(args.library))
    try:
        if args.cmd == "import":
            b = lib.import_files([Path(f) for f in args.files])
            print(json.dumps(b.model_dump(), indent=2))
        elif args.cmd == "import-folder":
            b = lib.import_folder(args.folder)
            print(json.dumps(b.model_dump(), indent=2))
        elif args.cmd == "analyze":
            print(Worker(lib.cfg, lib.repo).run_until_idle())
        elif args.cmd == "status":
            print(json.dumps({"assets": lib.count_assets(), "jobs": lib.job_summary(),
                              "capabilities": lib.capabilities(), "recovery": lib.recovery}, indent=2))
        elif args.cmd == "search":
            try:
                _print_hits(lib.search(args.query, limit=args.limit, collapse_duplicates=not args.expand_duplicates),
                            args.json)
            except SearchError as e:
                print(f"query error: {e}", file=sys.stderr)
                return 2
        elif args.cmd == "similar":
            crop = tuple(float(x) for x in args.crop.split(",")) if args.crop else None
            _print_hits(lib.find_similar(args.asset_id, crop=crop), args.json)
        elif args.cmd == "collections":
            for c in lib.collections():
                print(f"{c.ctype:10s} {c.member_count:4d}  {c.label}  ({c.id})")
        elif args.cmd == "refresh":
            print(json.dumps(lib.refresh_organization(inline=True), indent=2, default=str))
        elif args.cmd == "retry-failed":
            print(lib.retry_failed())
        elif args.cmd == "export":
            cids = None
            if args.collection:
                col = lib.collection(args.collection)
                if col is None:
                    print(f"collection {args.collection} not found", file=sys.stderr)
                    return 2
                cids = [col.id]
            ref = lib.export_snapshot(collection_ids=cids, metadata_format="1.0-projection" if args.v1 else "1.1",
                                      include_filenames=args.filenames)
            print(json.dumps(ref.model_dump(), indent=2))
    finally:
        lib.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
