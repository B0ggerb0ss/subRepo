"""Gradio Collections tab: smart sets, similarity groups, duplicate candidates,
corrections and export. Handlers call ``Library`` methods only."""
from __future__ import annotations

import json

import gradio as gr

from services.library.repository import StaleRevisionError
from services.organize.overrides import CorrectionError

TYPE_LABEL = {"smart": "Smart set", "similarity": "Similarity group", "duplicate": "Duplicate candidates",
              "user": "My collection"}


def _thumb(lib, asset_id: str):
    a = lib.get_asset(asset_id)
    p = lib.path_of(a.thumb_ref) if a else None
    return str(p) if p else None


def collection_choices(lib, ctype: str | None):
    cols = lib.collections(ctype=None if ctype in (None, "all") else ctype)
    out = []
    for c in cols:
        if c.member_count == 0 and c.ctype != "user":
            continue
        pin = "📌 " if c.pinned else ""
        out.append((f"{pin}{TYPE_LABEL[c.ctype]} · {c.label} ({c.member_count})", c.id))
    return out


def collection_view(lib, cid: str | None):
    if not cid:
        return [], "_Choose a collection._", [], 0
    c = lib.collection(cid)
    if c is None:
        return [], "_Collection not found (merged or retired)._", [], 0
    items, rows = [], []
    for m in c.members:
        t = _thumb(lib, m.asset_id)
        state = {"suggested": "suggested", "confirmed": "✔ confirmed", "excluded": "✖ excluded"}[m.state]
        if t and m.state != "excluded":
            items.append((t, f"{state} · {m.asset_id[-6:]}"))
        aff = "" if m.affinity is None else f"{m.affinity:.3f}"
        rows.append([m.asset_id, m.state, m.method, aff, m.affinity_kind])
    head = (f"### {c.label}\n{TYPE_LABEL[c.ctype]} · `{c.id}` · revision {c.revision}"
            + (f" · suggested label: _{c.suggested_label}_" if c.user_label else "")
            + (" · 📌 pinned" if c.pinned else ""))
    if c.ctype == "similarity":
        head += ("\n\nAffinity is the cosine similarity to the group's medoid — a ranking signal, "
                 "not a probability.")
    elif c.ctype == "smart":
        from services.analyze.catalog import thresholds_version

        head += ("\n\nMembership comes from typed decisions at validation-selected thresholds "
                 f"(`{thresholds_version() or 'catalog default 0.80'}`) or from your corrections; each member's "
                 "probability kind is listed below (zero-shot or dev-calibrated — neither is a guarantee).")
    elif c.ctype == "duplicate":
        head += "\n\nCandidates only — nothing is deleted. Verify and exclude false matches."
    return items, head, rows, c.revision


def build_collections_tab(lib, tab=None) -> None:
    rev = gr.State(0)
    with gr.Row():
        with gr.Column(scale=3):
            ctype = gr.Radio(["all", "smart", "similarity", "duplicate", "user"], value="all", label="Show",
                             elem_id="ax-col-type")
            picker = gr.Dropdown(label="Collection", choices=collection_choices(lib, "all"), elem_id="ax-col-pick")
            with gr.Row():
                refresh_btn = gr.Button("Reload list", size="sm", elem_id="ax-col-reload")
                rebuild_btn = gr.Button("Rebuild groups & duplicates", size="sm", elem_id="ax-col-rebuild")
            rebuild_md = gr.Markdown(elem_id="ax-col-rebuild-msg")
            gr.Markdown("#### Correct")
            new_label = gr.Textbox(label="Rename to", elem_id="ax-col-label")
            rename_btn = gr.Button("Rename", size="sm", elem_id="ax-col-rename")
            with gr.Row():
                pin_btn = gr.Button("Pin / unpin", size="sm", elem_id="ax-col-pin")
                hide_btn = gr.Button("Hide", size="sm", elem_id="ax-col-hide")
            assets_in = gr.Textbox(label="Asset ids (comma separated) for member actions", elem_id="ax-col-assets")
            with gr.Row():
                confirm_btn = gr.Button("Confirm", size="sm", elem_id="ax-col-confirm")
                exclude_btn = gr.Button("Exclude", size="sm", elem_id="ax-col-exclude")
                split_btn = gr.Button("Split into new group", size="sm", elem_id="ax-col-split")
            target = gr.Dropdown(label="Target collection (move / merge into)", choices=collection_choices(lib, "all"),
                                 elem_id="ax-col-target")
            with gr.Row():
                move_btn = gr.Button("Move assets to target", size="sm", elem_id="ax-col-move")
                merge_btn = gr.Button("Merge this into target", size="sm", elem_id="ax-col-merge")
            create_btn = gr.Button("Create my collection from asset ids", size="sm", elem_id="ax-col-create")
            gr.Markdown("#### Correct an image's metadata")
            with gr.Row():
                fix_asset = gr.Textbox(label="Asset id", elem_id="ax-fix-asset")
                fix_q = gr.Dropdown(label="Question", choices=_questions(), elem_id="ax-fix-q")
                fix_v = gr.Textbox(label="Value (option or yes/no)", elem_id="ax-fix-v")
            with gr.Row():
                fix_btn = gr.Button("Apply correction", size="sm", elem_id="ax-fix-apply")
                unfix_btn = gr.Button("Clear correction", size="sm", elem_id="ax-fix-clear")
            action_md = gr.Markdown(elem_id="ax-col-msg")
        with gr.Column(scale=5):
            head = gr.Markdown("_Choose a collection._", elem_id="ax-col-head")
            gallery = gr.Gallery(label="Members", columns=6, height=420, allow_preview=False, elem_id="ax-col-gallery")
            members = gr.Dataframe(headers=["asset_id", "state", "method", "affinity", "affinity_kind"],
                                   interactive=False, elem_id="ax-col-members")
            gr.Markdown("#### Export")
            with gr.Row():
                exp_scope = gr.Radio(["this collection", "whole library"], value="this collection", label="Scope",
                                     elem_id="ax-exp-scope")
                exp_fmt = gr.Radio(["1.1", "1.0-projection"], value="1.1", label="Metadata format",
                                   elem_id="ax-exp-fmt")
                exp_names = gr.Checkbox(label="Include original filenames", value=False, elem_id="ax-exp-names")
            exp_btn = gr.Button("Export snapshot", elem_id="ax-export")
            exp_file = gr.File(label="Snapshot", elem_id="ax-export-file")
            exp_md = gr.Markdown(elem_id="ax-export-msg")

    # The "Rename to" box is never written by view refreshes: a late refresh (e.g. after the
    # collection list reloads) must not overwrite a name the user is typing.
    view_out = [gallery, head, members, rev]

    def _choices(t):
        ch = collection_choices(lib, t)
        return gr.update(choices=ch, value=None), gr.update(choices=collection_choices(lib, "all"))

    def _ids(text):
        return [x.strip() for x in (text or "").split(",") if x.strip()]

    def _do(cmd, expected, cid):
        try:
            res = lib.correct(cmd, expected_revision=expected)
            msg = f"✔ {cmd['op']} applied ({len(res.correction_ids)} correction record(s))."
            new_cid = res.collection_id or cid
        except StaleRevisionError as e:
            msg, new_cid = f"⚠️ Not applied — {e}. Reloaded the latest state; please retry.", cid
        except (CorrectionError, ValueError) as e:
            msg, new_cid = f"⚠️ {e}", cid
        ch = collection_choices(lib, "all")
        return (msg, gr.update(choices=ch, value=new_cid), gr.update(choices=ch), *collection_view(lib, new_cid))

    act_out = [action_md, picker, target] + view_out
    ctype.change(_choices, [ctype], [picker, target])
    refresh_btn.click(_choices, [ctype], [picker, target])
    if tab is not None:
        # Tab contents mount lazily and the list built at startup may be stale:
        # refresh whenever the user opens the tab.
        tab.select(lambda t: (gr.update(choices=collection_choices(lib, t)),
                              gr.update(choices=collection_choices(lib, "all"))), [ctype], [picker, target])
    picker.change(lambda c: collection_view(lib, c), [picker], view_out)
    rename_btn.click(lambda c, r, l: _do({"op": "rename", "collection_id": c, "label": l}, r, c),
                     [picker, rev, new_label], act_out)

    def _pin(c, r):
        col = lib.collection(c) if c else None
        return _do({"op": "pin", "collection_id": c, "value": not (col and col.pinned)}, r, c)

    pin_btn.click(_pin, [picker, rev], act_out)
    hide_btn.click(lambda c, r: _do({"op": "hide", "collection_id": c, "value": True}, r, None), [picker, rev], act_out)
    confirm_btn.click(lambda c, r, a: _do({"op": "confirm", "collection_id": c, "asset_ids": _ids(a)}, r, c),
                      [picker, rev, assets_in], act_out)
    exclude_btn.click(lambda c, r, a: _do({"op": "exclude", "collection_id": c, "asset_ids": _ids(a)}, r, c),
                      [picker, rev, assets_in], act_out)
    split_btn.click(lambda c, r, a, l: _do({"op": "split", "collection_id": c, "asset_ids": _ids(a), "label": l},
                                           r, c), [picker, rev, assets_in, new_label], act_out)
    move_btn.click(lambda c, t, a: _do({"op": "move", "collection_id": c, "to": t, "asset_ids": _ids(a)}, None, t),
                   [picker, target, assets_in], act_out)
    merge_btn.click(lambda c, t: _do({"op": "merge", "into": t, "collection_ids": [c]}, None, t),
                    [picker, target], act_out)
    create_btn.click(lambda a, l: _do({"op": "create", "asset_ids": _ids(a), "label": l or "My collection"}, None,
                                      None), [assets_in, new_label], act_out)
    fix_btn.click(lambda a, q, v, c: _do({"op": "set_decision", "asset_id": (a or "").strip(), "question_id": q,
                                          "value": (v or "").strip()}, None, c),
                  [fix_asset, fix_q, fix_v, picker], act_out)
    unfix_btn.click(lambda a, q, c: _do({"op": "clear_decision", "asset_id": (a or "").strip(), "question_id": q},
                                        None, c), [fix_asset, fix_q, picker], act_out)

    def _rebuild():
        job = lib.refresh_organization()
        return (f"Queued rebuild job `{job}`. Smart sets update on every analysis; similarity groups and duplicate "
                "candidates are rebuilt by this job (your corrections are kept).")

    rebuild_btn.click(_rebuild, None, [rebuild_md])

    def _export(c, scope, fmt, names):
        if scope == "this collection" and not c:
            return None, "Choose a collection or export the whole library."
        ref = lib.export_snapshot(collection_ids=[c] if scope == "this collection" else None,
                                  metadata_format=fmt, include_filenames=bool(names))
        path = lib.cfg.library_root / ref.relative_path
        return str(path), (f"Exported `{ref.export_id}`: {ref.assets} image(s), {ref.collections} collection(s), "
                           f"{ref.bytes} bytes, sha256 `{ref.sha256[:16]}…`. Filenames "
                           f"{'included' if names else 'excluded'}; EXIF camera fields and notes excluded.")

    exp_btn.click(_export, [picker, exp_scope, exp_fmt, exp_names], [exp_file, exp_md])


def _questions():
    from services.analyze.catalog import catalog

    return [q for q in catalog()["questions"] if not q.startswith("sufficiency.")]
