"""Asset admission: validate, hash, copy immutably, register, enqueue analysis.

- Originals are copied into ``originals/<h[:2]>/<sha256>.<ext>`` via a temp
  file + atomic rename and made read-only. The user's source file is never
  modified or deleted.
- Identical bytes within a library map to one Asset (so extraction is reused);
  every import still gets its own ImportInstance with its original filename.
- A bad file is rejected with a sanitized code/message and the rest of the
  batch continues.
- Folder import walks only an explicitly chosen directory, never follows
  symlinks (so no escapes or loops) and enforces a depth/file limit.
- Videos (mp4/mov/m4v/webm/mkv) are admitted after an ffprobe check (video
  stream present, duration and size limits) and become ``kind='video'`` assets
  analyzed through sampled keyframes (services/analyze/video.py).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
import uuid
from pathlib import Path

from models.asset import ImportBatch, Rejection
from services.analyze.pixels import ImageAdmissionError, probe_image
from services.analyze.videoio import VIDEO_SUFFIXES, probe_video
from services.library.config import LibraryConfig
from services.library.jobs import JobQueue
from services.library.repository import Repository

EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def asset_id_for(library_id: str, content_hash: str) -> str:
    return "ast_" + hashlib.sha256(f"{library_id}:{content_hash}".encode()).hexdigest()[:20]


def _sanitize_name(name: str) -> str:
    # Keep only the final component; never store a host directory path.
    base = Path(name).name
    return "".join(ch for ch in base if ch.isprintable())[:255] or "unnamed"


def _copy_and_hash(src: Path, tmp_root: Path) -> tuple[Path, str, int]:
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f"import-{uuid.uuid4().hex}.part"
    h = hashlib.sha256()
    n = 0
    with src.open("rb") as fin, tmp.open("wb") as fout:
        for chunk in iter(lambda: fin.read(1 << 20), b""):
            h.update(chunk)
            fout.write(chunk)
            n += len(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    return tmp, h.hexdigest(), n


def _walk_folder(root: Path, cfg: LibraryConfig, rejections: list[Rejection]) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("selected folder does not exist")
    files: list[Path] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        if len(d.parts) - base_depth >= cfg.limits.max_folder_depth:
            dirnames[:] = []
        dirnames[:] = sorted(x for x in dirnames if not x.startswith("."))
        for fn in sorted(filenames):
            p = d / fn
            if p.is_symlink():
                rejections.append(Rejection(filename=fn, code="symlink_skipped",
                                            message="symbolic links are not followed"))
                continue
            if fn.startswith(".") or p.suffix.lower() not in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
                continue
            files.append(p)
            if len(files) >= cfg.limits.max_batch_files:
                rejections.append(Rejection(filename=str(root.name), code="batch_limit",
                                            message=f"stopped after {cfg.limits.max_batch_files} files"))
                return files
    return files


def import_assets(
    inputs: list[str | Path] | str | Path,
    repo: Repository,
    cfg: LibraryConfig,
    queue: JobQueue,
    source_kind: str = "files",
    display_names: dict[str, str] | None = None,
    source_note: str | None = None,
    enqueue: bool = True,
) -> ImportBatch:
    """Admit files (or one explicitly selected folder) into the library.

    ``display_names`` maps an input path to the user-facing original filename
    (Gradio uploads arrive under temp names).
    """
    cfg.ensure_dirs()
    batch_id = f"imp_{uuid.uuid4().hex[:16]}"
    rejections: list[Rejection] = []
    if source_kind == "folder":
        folder = Path(inputs if not isinstance(inputs, list) else inputs[0])
        paths = _walk_folder(folder, cfg, rejections)
        path_hint_root = folder.resolve()
    else:
        paths = [Path(p) for p in (inputs if isinstance(inputs, list) else [inputs])]
        path_hint_root = None

    now = time.time()
    with repo.write() as c:
        c.execute(
            "INSERT INTO import_batches(id, library_id, created_at, source_kind, status)"
            " VALUES (?,?,?,?,?)", (batch_id, cfg.library_id, now, source_kind, "running"))

    admitted = reused = 0
    asset_ids: list[str] = []
    job_ids: list[str] = []
    for src in paths:
        name = _sanitize_name((display_names or {}).get(str(src), src.name))
        try:
            if src.is_symlink() or not src.is_file():
                raise ImageAdmissionError("not_a_file", "not a regular file")
            if src.suffix.lower() in VIDEO_SUFFIXES:
                kind = "video"
                info = probe_video(src, cfg.limits.max_video_bytes, cfg.limits.max_video_seconds)
            else:
                kind = "image"
                info = probe_image(src, cfg.limits.max_image_bytes, cfg.limits.max_image_pixels)
            tmp, digest, nbytes = _copy_and_hash(src, cfg.temp_root)
        except ImageAdmissionError as e:
            rejections.append(Rejection(filename=name, code=e.code, message=str(e)))
            continue
        except OSError:
            rejections.append(Rejection(filename=name, code="io_error", message="file could not be read"))
            continue

        aid = asset_id_for(cfg.library_id, digest)
        ext = EXTENSIONS[info["format"]] if kind == "image" else info["ext"]
        rel = f"originals/{digest[:2]}/{digest}.{ext}"
        dest = cfg.library_root / rel
        try:
            if dest.exists():
                tmp.unlink(missing_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, dest)
                os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            tmp.unlink(missing_ok=True)
            rejections.append(Rejection(filename=name, code="storage_error",
                                        message="could not store the original (disk full?)"))
            continue

        path_hint = None
        if path_hint_root is not None:
            try:
                path_hint = str(src.resolve().relative_to(path_hint_root).parent)
            except ValueError:
                path_hint = None
        with repo.write() as c:
            existing = c.execute("SELECT id, deleted_at, metadata_revision FROM assets WHERE id=?",
                                 (aid,)).fetchone()
            if existing is None:
                c.execute(
                    "INSERT INTO assets(id, library_id, content_hash, kind, mime, byte_size, width, height,"
                    " original_ref, created_at, duration_s) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, cfg.library_id, digest, kind, info["mime"], nbytes, info["width"],
                     info["height"], rel, time.time(), info.get("duration_s")))
                admitted += 1
                needs_analysis = True
            else:
                reused += 1
                if existing["deleted_at"] is not None:
                    c.execute("UPDATE assets SET deleted_at=NULL WHERE id=?", (aid,))
                needs_analysis = existing["metadata_revision"] == 0
            c.execute(
                "INSERT INTO import_instances(id, asset_id, batch_id, library_id, original_filename,"
                " path_hint, source_note, imported_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"ii_{uuid.uuid4().hex[:16]}", aid, batch_id, cfg.library_id, name, path_hint,
                 source_note, time.time()))
            c.execute("INSERT OR IGNORE INTO user_annotations(asset_id, updated_at) VALUES (?,?)",
                      (aid, time.time()))
            if enqueue and needs_analysis:
                active = c.execute("SELECT id FROM jobs WHERE asset_id=? AND status IN ('queued','running')",
                                   (aid,)).fetchone()
                if active is None:
                    from services.analyze.pipeline import planned_stages

                    job_ids.append(queue.enqueue("analyze_image", aid, planned_stages(kind), conn=c))
                else:
                    job_ids.append(active["id"])
        asset_ids.append(aid)

    status = "complete" if not rejections else ("failed" if not asset_ids else "partial")
    with repo.write() as c:
        c.execute(
            "UPDATE import_batches SET total=?, admitted=?, reused=?, rejected=?, status=? WHERE id=?",
            (len(paths) + sum(1 for r in rejections if r.code in {"symlink_skipped"}),
             admitted, reused, len(rejections), status, batch_id))
        c.executemany(
            "INSERT INTO import_rejections(batch_id, filename, code, message) VALUES (?,?,?,?)",
            [(batch_id, r.filename, r.code, r.message) for r in rejections])
    return ImportBatch(
        id=batch_id, library_id=cfg.library_id, source_kind=source_kind,
        total=len(paths), admitted=admitted, reused=reused, rejected=len(rejections),
        status=status, asset_ids=asset_ids, job_ids=job_ids, rejections=rejections,
    )


def cleanup_temp_root(cfg: LibraryConfig, older_than_s: float = 0) -> int:
    """Remove stale import temp files. Only ever touches the managed temp root."""
    n = 0
    now = time.time()
    if not cfg.temp_root.is_dir():
        return 0
    for p in cfg.temp_root.iterdir():
        if p.is_file() and p.suffix == ".part" and now - p.stat().st_mtime >= older_than_s:
            p.unlink(missing_ok=True)
            n += 1
        elif p.is_dir() and now - p.stat().st_mtime >= older_than_s:
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n
