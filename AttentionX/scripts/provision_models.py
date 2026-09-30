#!/usr/bin/env python3
"""Explicit, pinned model provisioning for the AttentionX image library.

Usage:
  python scripts/provision_models.py                   # download + verify all
  python scripts/provision_models.py --only minilm_l6_v2
  python scripts/provision_models.py --from-dir DIR    # verify local copies, no network
  python scripts/provision_models.py --check           # report status, no writes
  python scripts/provision_models.py --capabilities    # full runtime capability report

This is the only code path allowed to touch the network for models. Analysis
jobs never download. Every file is verified against docs/model-manifest.json
(sha256, plus upstream md5 where published) before PROVISIONED.json is written.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.library.config import get_config, load_manifest  # noqa: E402


def _hash(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, attempts: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            tmp.replace(dest)
            return
        except Exception as e:  # network errors: bounded exponential backoff
            if i == attempts - 1:
                raise RuntimeError(f"download failed for {url}: {e}") from e
            time.sleep(2 ** (i + 1))


def _verify(path: Path, spec: dict) -> None:
    if "size" in spec and path.stat().st_size != spec["size"]:
        raise RuntimeError(f"{path.name}: size {path.stat().st_size} != {spec['size']}")
    got = _hash(path, "sha256")
    if got != spec["sha256"]:
        raise RuntimeError(f"{path.name}: sha256 {got} != pinned {spec['sha256']}")
    if "md5_upstream" in spec and _hash(path, "md5") != spec["md5_upstream"]:
        raise RuntimeError(f"{path.name}: md5 does not match upstream")


def _locate(from_dir: Path | None, names: list[str]) -> Path | None:
    if from_dir is None:
        return None
    for n in names:
        for p in from_dir.rglob(n):
            if p.is_file():
                return p
    return None


def provision(name: str, spec: dict, from_dir: Path | None, dest_root: Path) -> dict:
    dest = dest_root / name
    staging = Path(tempfile.mkdtemp(prefix=f"prov-{name}-", dir=dest_root))
    try:
        if "archive" in spec:
            a = spec["archive"]
            archive = _locate(from_dir, [Path(a["url"]).name]) or staging / "archive"
            if not archive.exists():
                _download(a["url"], archive)
            _verify(archive, a)
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    rel = member.name
                    if not rel.startswith(a["strip_prefix"]):
                        continue
                    rel = rel[len(a["strip_prefix"]):]
                    if not rel or "/" in rel or rel.startswith(".") or rel.startswith("._"):
                        continue
                    if rel in spec["files"] and member.isfile():
                        data = tf.extractfile(member).read()
                        (staging / rel).write_bytes(data)
        for fname, fspec in spec["files"].items():
            target = staging / fname
            if target.exists():
                pass
            elif "extract_from_zip" in fspec:
                local = _locate(from_dir, [fname, Path(fspec["url"]).name])
                if local is not None and local.name == fname:
                    shutil.copyfile(local, target)
                else:
                    whl = local or staging / "archive.zip"
                    if not whl.exists():
                        _download(fspec["url"], whl)
                    if _hash(whl, "sha256") != fspec["archive_sha256"]:
                        raise RuntimeError(f"{whl.name}: archive sha256 mismatch")
                    with zipfile.ZipFile(whl) as z:
                        target.write_bytes(z.read(fspec["extract_from_zip"]))
            else:
                local = _locate(from_dir, [fname])
                if local is not None:
                    shutil.copyfile(local, target)
                elif "url" in fspec:
                    _download(fspec["url"], target)
                else:
                    raise RuntimeError(f"{fname}: no source available")
            _verify(target, fspec)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for fname in spec["files"]:
            (staging / fname).replace(dest / fname)
        stamp = {
            "model": name,
            "provisioned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "files": {f: s["sha256"] for f, s in spec["files"].items()},
            "manifest_entry": {k: v for k, v in spec.items() if k not in {"files", "archive"}},
        }
        (dest / "PROVISIONED.json").write_text(json.dumps(stamp, indent=2), encoding="utf-8")
        return {"model": name, "status": "provisioned"}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check(name: str, spec: dict, dest_root: Path, deep: bool) -> dict:
    d = dest_root / name
    if not (d / "PROVISIONED.json").is_file():
        return {"model": name, "status": "missing"}
    for fname, fspec in spec["files"].items():
        p = d / fname
        if not p.is_file():
            return {"model": name, "status": "corrupt", "detail": f"{fname} missing"}
        if deep:
            try:
                _verify(p, fspec)
            except RuntimeError as e:
                return {"model": name, "status": "corrupt", "detail": str(e)}
    return {"model": name, "status": "provisioned", "verified": deep}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--deep", action="store_true", help="re-hash files during --check")
    ap.add_argument("--capabilities", action="store_true")
    args = ap.parse_args()

    cfg = get_config()
    if args.capabilities:
        from services.analyze.capabilities import capability_report

        print(json.dumps(capability_report(cfg, deep=args.deep), indent=2))
        return 0

    manifest = load_manifest()["models"]
    names = args.only or list(manifest)
    cfg.model_root.mkdir(parents=True, exist_ok=True)
    results = []
    ok = True
    for name in names:
        if name not in manifest:
            print(f"unknown model {name}", file=sys.stderr)
            return 2
        try:
            r = (check(name, manifest[name], cfg.model_root, args.deep) if args.check
                 else provision(name, manifest[name], args.from_dir, cfg.model_root))
        except Exception as e:
            r = {"model": name, "status": "error", "detail": str(e)}
        ok &= r["status"] == "provisioned"
        results.append(r)
    print(json.dumps(results, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
