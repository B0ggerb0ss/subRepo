"""Gradio Library tab: import, gallery, search, inspector, annotations.

Handlers are thin: they call ``services.library.registry.Library`` and render
its typed results. ``gr.State`` holds only ids and serialized hits.
"""
from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
from PIL import Image, ImageDraw

from models.search import SearchHit
from services.search.service import SearchError
from ui.inspector import evidence_markdown, render_inspector_image

PAGE = 40
# Listing events share one ordered queue slot: a slow earlier listing (e.g. the
# initial page load) can never overwrite the results of a later search.
LISTING = {"concurrency_id": "library_listing", "concurrency_limit": 1}
_SEARCH_SEQ = __import__("itertools").count(1)
STATUS_BADGE = {"complete": "✅", "partial": "⚠️", "error": "❌", "pending": "⏳"}


def _placeholder(lib, text: str) -> str:
    p = lib.cfg.library_root / "derived" / "ui" / f"placeholder_{text}.png"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (256, 256), (230, 230, 230))
        ImageDraw.Draw(im).text((90, 120), text, fill=(90, 90, 90))
        im.save(p)
    return str(p)


def _thumb(lib, asset: dict) -> str:
    p = lib.path_of(asset.get("thumb_ref"))
    return str(p) if p else _placeholder(lib, "pending")


def capability_markdown(lib) -> str:
    parts = []
    for c in lib.capabilities():
        icon = "🟢" if c["available"] else ("⚪" if not c["enabled"] else "🔴")
        parts.append(f"{icon} **{c['name']}** {c['code']}")
    jobs = lib.job_summary()
    queue = ", ".join(f"{k}: {v}" for k, v in sorted(jobs.items())) or "no jobs"
    return " · ".join(parts) + f"\n\n**Jobs** — {queue}"


def fresh(items):
    """New gallery contents with the first item selected.

    Gradio keeps a stale selected index across value updates (and drops
    ``selected_index=None``), so clicking the new first item would fire no select
    event. Every new listing therefore selects and inspects its first item."""
    return gr.update(value=items, selected_index=0) if items else gr.update(value=items)


def gallery_items(lib, offset: int = 0):
    assets = lib.list_assets(offset=offset, limit=PAGE)
    items = [(_thumb(lib, a), f"{STATUS_BADGE.get(a['status'], '')} {a['filename'] or a['id']}") for a in assets]
    ids = [a["id"] for a in assets]
    return items, ids


def _caption(lib, hit: SearchHit, names: dict[str, str]) -> str:
    codes = sorted({e.reason for e in hit.reasons})
    dup = f" (+{hit.duplicate_count} dup)" if hit.duplicate_count else ""
    return f"{names.get(hit.asset_id, hit.asset_id)} · {', '.join(codes)}{dup}"


def run_search(lib, query: str, collapse: bool, offset: int):
    try:
        resp = lib.search(query, limit=PAGE, offset=offset, collapse_duplicates=collapse)
    except SearchError as e:
        return gr.update(), [], f"Search #{next(_SEARCH_SEQ)} · ⚠️ **Query error:** {e}", offset
    ids = [h.asset_id for h in resp.hits]
    names = {}
    for aid in ids:
        d = lib.repo.query_one("SELECT original_filename FROM import_instances WHERE asset_id=? ORDER BY imported_at"
                               " LIMIT 1", (aid,))
        names[aid] = d["original_filename"] if d else aid
    items = []
    for h in resp.hits:
        a = lib.get_asset(h.asset_id)
        items.append((_thumb(lib, a.model_dump()), _caption(lib, h, names)))
    notes = [f"Search #{next(_SEARCH_SEQ)} · **{resp.total_candidates}** result(s) · channels: "
             f"{', '.join(resp.channels_used) or 'filters only'} · {resp.elapsed_ms:.0f} ms"]
    notes += [f"⚠️ {d}" for d in resp.degraded]
    if resp.total_candidates > offset + PAGE:
        notes.append(f"Showing {offset + 1}–{offset + len(resp.hits)}; use Next page.")
    return items, [h.model_dump(mode="json") for h in resp.hits], "\n\n".join(notes), offset


def inspector_outputs(lib, asset_id: str | None, hit_json: dict | None, show_all_ocr: bool = False):
    if not asset_id:
        return None, "", "", {}, [], "", "", "", 0, ""
    hit = SearchHit.model_validate(hit_json) if hit_json else None
    image = render_inspector_image(lib, asset_id, hit, show_all_ocr=show_all_ocr)
    detail = lib.asset_detail(asset_id)
    meta = detail["metadata"] or {}
    ocr = meta.get("ocr") or {}
    ocr_lines = "\n".join(r["raw_text"] for r in sorted(ocr.get("regions", []), key=lambda r: r["reading_order"]))
    if ocr and not ocr.get("complete"):
        ocr_lines = f"[incomplete OCR coverage: {ocr.get('incomplete_reason')}]\n" + ocr_lines
    if not ocr:
        ocr_lines = f"[OCR {meta.get('stage_status', {}).get('ocr', 'pending')}]"
    stages = []
    for j in detail["jobs"][:1]:
        stages = [[s["stage"], s["status"], s["detail"] or ""] for s in j["stages"]]
    ann = detail["annotations"]
    names = ", ".join(i["original_filename"] for i in detail["imports"])
    head = (f"**{names}** · `{asset_id}` · status {STATUS_BADGE.get(detail['status'], '')} {detail['status']}"
            f" · revision {detail['asset']['metadata_revision']}")
    decisions = meta.get("decisions") or {}
    dec_lines = []
    for qid, d in sorted(decisions.items()):
        if d["status"] == "complete":
            val = d["value"] if isinstance(d["value"], str) else f"P(yes)={d['value']:.2f}"
            dec_lines.append(f"- `{qid}`: {val} ({d['probability_kind']})")
        else:
            dec_lines.append(f"- `{qid}`: {d['status']} — {d.get('abstain_reason') or ''}")
    for q, v in detail["overrides"].items():
        dec_lines.append(f"- `{q}` **corrected by you → {v}**")
    ev = evidence_markdown(hit) if hit else "_Selected from the gallery; run a search to see match evidence._"
    if dec_lines:
        ev += "\n\n**Typed decisions** (uncalibrated unless stated)\n" + "\n".join(dec_lines)
    return (image, head, ev, meta, stages, ann["title"], ann["notes"], ", ".join(ann["tags"]), ann["revision"],
            ocr_lines)


def build_library_tab(lib) -> None:
    hits_state = gr.State([])
    ids_state = gr.State([])
    selected = gr.State(None)
    selected_hit = gr.State(None)
    offset_state = gr.State(0)

    caps = gr.Markdown(capability_markdown(lib), elem_id="ax-capabilities")
    with gr.Row():
        with gr.Column(scale=4):
            with gr.Accordion("Import", open=True):
                upload = gr.File(label="Images (JPEG, PNG, WebP)", file_count="multiple",
                                 file_types=[".jpg", ".jpeg", ".png", ".webp"], elem_id="ax-upload")
                import_btn = gr.Button("Import files", variant="primary", elem_id="ax-import")
                folder = gr.Textbox(label="Or import an explicitly selected local folder", placeholder="/path/to/folder",
                                    elem_id="ax-folder")
                folder_btn = gr.Button("Import folder", elem_id="ax-import-folder")
                import_md = gr.Markdown(elem_id="ax-import-result")
            with gr.Row():
                query = gr.Textbox(label="Search", placeholder='text:"feature store"  ·  rainy street at night  ·  '
                                   'source:linkedin text:"hiring"', scale=5, elem_id="ax-query")
                search_btn = gr.Button("Search", variant="primary", scale=1, elem_id="ax-search")
            with gr.Row():
                collapse = gr.Checkbox(label="Collapse near-duplicates", value=True, elem_id="ax-collapse")
                prev_btn = gr.Button("◀ Prev page", size="sm", elem_id="ax-prev")
                next_btn = gr.Button("Next page ▶", size="sm", elem_id="ax-next")
                refresh_btn = gr.Button("Refresh", size="sm", elem_id="ax-refresh")
            notes = gr.Markdown(elem_id="ax-search-notes")
            gallery = gr.Gallery(label="Library", columns=5, height=520, allow_preview=False, elem_id="ax-gallery")
        with gr.Column(scale=5):
            head = gr.Markdown("_Select an image to inspect it._", elem_id="ax-inspector-head")
            with gr.Row():
                show_all = gr.Checkbox(label="Show all OCR boxes", value=False, elem_id="ax-show-all-ocr")
            inspector_img = gr.Image(label="Inspector", interactive=False, height=460, elem_id="ax-inspector")
            with gr.Tabs():
                with gr.Tab("Evidence"):
                    evidence = gr.Markdown(elem_id="ax-evidence")
                with gr.Tab("OCR text"):
                    ocr_text = gr.Textbox(label="Recognized text (verbatim, reading order)", lines=10,
                                          interactive=False, elem_id="ax-ocr-text")
                with gr.Tab("Stages"):
                    stages = gr.Dataframe(headers=["stage", "status", "detail"], interactive=False,
                                          elem_id="ax-stages")
                    with gr.Row():
                        retry_btn = gr.Button("Retry analysis", size="sm", elem_id="ax-retry")
                        cancel_btn = gr.Button("Cancel running job", size="sm", elem_id="ax-cancel")
                        delete_btn = gr.Button("Remove from library", size="sm", variant="stop",
                                               elem_id="ax-delete")
                    stage_msg = gr.Markdown(elem_id="ax-stage-msg")
                with gr.Tab("Annotations"):
                    title = gr.Textbox(label="Title", elem_id="ax-title")
                    note = gr.Textbox(label="Notes", lines=3, elem_id="ax-notes")
                    tags = gr.Textbox(label="Tags (comma separated)", elem_id="ax-tags")
                    ann_rev = gr.Number(label="Revision", interactive=False, precision=0, elem_id="ax-ann-rev")
                    save_btn = gr.Button("Save annotations", elem_id="ax-save-ann")
                    save_msg = gr.Markdown(elem_id="ax-save-msg")
                with gr.Tab("Metadata"):
                    meta_json = gr.JSON(label="Active metadata revision (MediaMetadata/1.1)", elem_id="ax-meta")
                with gr.Tab("Similar"):
                    gr.Markdown("Find visually similar images. Optionally restrict to a region "
                                "(normalized 0–1 box on the displayed image). Similarity is ranked, not a "
                                "detector result.")
                    with gr.Row():
                        cx0 = gr.Number(label="x0", value=0.0, minimum=0, maximum=1, elem_id="ax-cx0")
                        cy0 = gr.Number(label="y0", value=0.0, minimum=0, maximum=1, elem_id="ax-cy0")
                        cx1 = gr.Number(label="x1", value=1.0, minimum=0, maximum=1, elem_id="ax-cx1")
                        cy1 = gr.Number(label="y1", value=1.0, minimum=0, maximum=1, elem_id="ax-cy1")
                    similar_btn = gr.Button("Find similar", elem_id="ax-similar")
    timer = gr.Timer(3.0)

    inspector_out = [inspector_img, head, evidence, meta_json, stages, title, note, tags, ann_rev, ocr_text]

    def _inspect_first(listing, show=False):
        """(gallery, ids, hits, notes, offset) -> + (selected, selected_hit, *inspector) for the first item."""
        gal, ids, hits, msg, off = listing
        if not isinstance(ids, list):  # error path: leave selection and inspector untouched
            return (gal, ids, hits, msg, off, gr.update(), gr.update(), *[gr.update()] * len(inspector_out))
        aid = ids[0] if ids else None
        hit = next((h for h in hits if h["asset_id"] == aid), None) if aid else None
        return (gal, ids, hits, msg, off, aid, hit, *inspector_outputs(lib, aid, hit, show))

    def _browse(offset=0):
        items, ids = gallery_items(lib, offset)
        return fresh(items), ids, [], f"{lib.count_assets()} image(s) in the library.", offset

    def _import(files):
        if not files:
            return "Choose one or more images first.", *_browse()[:4]
        paths = [f if isinstance(f, str) else f.name for f in files]
        names = {p: Path(p).name for p in paths}
        batch = lib.import_files(paths, display_names=names)
        return _batch_md(batch), *_browse()[:4]

    def _import_folder(path):
        if not path or not path.strip():
            return "Enter a folder path.", *_browse()[:4]
        try:
            batch = lib.import_folder(path.strip())
        except ValueError as e:
            return f"⚠️ {e}", *_browse()[:4]
        return _batch_md(batch), *_browse()[:4]

    def _batch_md(batch):
        md = (f"Imported batch `{batch.id}`: **{batch.admitted} new**, {batch.reused} already in library, "
              f"{batch.rejected} rejected. Analysis queued for {len(batch.job_ids)} image(s).")
        if batch.rejections:
            md += "\n" + "\n".join(f"- `{r.filename}`: {r.code} — {r.message}" for r in batch.rejections[:20])
        return md

    def _search(q, coll, offset=0):
        if not (q or "").strip():
            items, ids, hits, msg, off = _browse(0)
            return items, ids, hits, msg, 0
        items, hits, msg, off = run_search(lib, q, coll, offset)
        if isinstance(items, dict):
            return gr.update(), gr.update(), gr.update(), msg, offset
        return fresh(items), [h["asset_id"] for h in hits], hits, msg, off

    def _select(evt: gr.SelectData, ids, hits, show):
        idx = evt.index
        if idx is None or idx >= len(ids):
            return None, None, *inspector_outputs(lib, None, None)
        aid = ids[idx]
        hit = next((h for h in hits if h["asset_id"] == aid), None)
        return aid, hit, *inspector_outputs(lib, aid, hit, show)

    def _reinspect(aid, hit, show):
        return inspector_outputs(lib, aid, hit, show)

    def _save(aid, t, n, tg, rev, hit, show):
        if not aid:
            return "Select an image first.", *inspector_outputs(lib, None, None)
        from services.library.repository import StaleRevisionError

        try:
            lib.set_annotations(aid, int(rev or 0), title=t, notes=n, tags=[x for x in (tg or "").split(",")])
            msg = "Saved."
        except StaleRevisionError as e:
            msg = f"⚠️ Not saved: {e}. Reloaded the latest values."
        return msg, *inspector_outputs(lib, aid, hit, show)

    def _retry(aid):
        if not aid:
            return "Select an image first."
        job = lib.retry_asset(aid)
        return f"Queued job `{job}`; unchanged stages will be served from cache."

    def _cancel(aid):
        if not aid:
            return "Select an image first."
        jobs = [j for j in lib.jobs_for(aid) if j.status in {"queued", "running"}]
        if not jobs:
            return "No queued or running job for this image."
        ok = lib.cancel_job(jobs[0].id)
        return f"Cancellation {'requested' if ok else 'not possible'} for `{jobs[0].id}`."

    def _delete(aid):
        if not aid:
            return "Select an image first.", *_browse()[:4]
        lib.delete_asset(aid)
        return ("Removed from the library (search excludes it now). Your original file was not touched; "
                "the managed copy is kept until purged."), *_browse()[:4]

    def _similar(aid, x0, y0, x1, y1, coll):
        if not aid:
            return gr.update(), gr.update(), gr.update(), "Select an image first.", 0
        crop = None
        box = tuple(float(v or 0) for v in (x0, y0, x1, y1))
        if box != (0.0, 0.0, 1.0, 1.0):
            if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                return gr.update(), gr.update(), gr.update(), "⚠️ Crop must satisfy 0 ≤ x0 < x1 ≤ 1 and 0 ≤ y0 < y1 ≤ 1.", 0
            crop = box
        try:
            resp = lib.find_similar(aid, crop=crop, limit=PAGE)
        except SearchError as e:
            return gr.update(), gr.update(), gr.update(), f"⚠️ {e}", 0
        items = [(_thumb(lib, lib.get_asset(h.asset_id).model_dump()),
                  ", ".join(sorted({e.reason for e in h.reasons}))) for h in resp.hits]
        msg = [f"Similar to `{aid}`" + (f" (crop {crop})" if crop else "") + f": {resp.total_candidates} result(s)."]
        msg += [f"⚠️ {d}" for d in resp.degraded]
        return fresh(items), [h.asset_id for h in resp.hits], [h.model_dump(mode="json") for h in resp.hits], \
            "\n\n".join(msg), 0

    def _tick(aid, hit, show):
        return capability_markdown(lib)

    list_out = [gallery, ids_state, hits_state, notes, offset_state, selected, selected_hit] + inspector_out
    first = _inspect_first

    def _with_msg(fn):
        def run(*a):
            msg, *listing = fn(*a)
            out = first((*listing, 0))
            return (msg, *out[:4], *out[5:])  # drop the offset slot
        return run

    import_btn.click(_with_msg(_import), [upload],
                     [import_md, gallery, ids_state, hits_state, notes, selected, selected_hit] + inspector_out,
                     **LISTING)
    folder_btn.click(_with_msg(_import_folder), [folder],
                     [import_md, gallery, ids_state, hits_state, notes, selected, selected_hit] + inspector_out,
                     **LISTING)
    search_btn.click(lambda q, c: first(_search(q, c, 0)), [query, collapse], list_out, **LISTING)
    query.submit(lambda q, c: first(_search(q, c, 0)), [query, collapse], list_out, **LISTING)
    next_btn.click(lambda q, c, o: first(_search(q, c, o + PAGE) if (q or "").strip() else _browse(o + PAGE)),
                   [query, collapse, offset_state], list_out, **LISTING)
    prev_btn.click(lambda q, c, o: first(_search(q, c, max(0, o - PAGE)) if (q or "").strip()
                                         else _browse(max(0, o - PAGE))),
                   [query, collapse, offset_state], list_out, **LISTING)
    refresh_btn.click(lambda q, c, o: first(_search(q, c, o) if (q or "").strip() else _browse(o)),
                      [query, collapse, offset_state], list_out, **LISTING)
    gallery.select(_select, [ids_state, hits_state, show_all], [selected, selected_hit] + inspector_out)
    show_all.change(_reinspect, [selected, selected_hit, show_all], inspector_out)
    save_btn.click(_save, [selected, title, note, tags, ann_rev, selected_hit, show_all], [save_msg] + inspector_out)
    retry_btn.click(_retry, [selected], [stage_msg])
    cancel_btn.click(_cancel, [selected], [stage_msg])
    delete_btn.click(_with_msg(_delete), [selected],
                     [stage_msg, gallery, ids_state, hits_state, notes, selected, selected_hit] + inspector_out,
                     **LISTING)
    similar_btn.click(lambda *a: first(_similar(*a)), [selected, cx0, cy0, cx1, cy1, collapse], list_out,
                      **LISTING)
    timer.tick(_tick, [selected, selected_hit, show_all], [caps])

    # Expose a few components for other tabs (collections) to reuse.
    build_library_tab.components = {"query": query, "gallery": gallery, "selected": selected, "ids": ids_state,
                                    "notes": notes}
