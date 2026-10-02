"""Collection lookup helpers shared by search and the correction commands."""
from __future__ import annotations

from services.library.repository import Repository


def resolve_collection_id(repo: Repository, key_or_id: str) -> str | None:
    """Resolve a collection by id, key or label, following merge/split aliases."""
    r = repo.query_one(
        "SELECT id FROM collections WHERE retired_at IS NULL AND (id=? OR key=? OR lower(COALESCE(user_label,''))=?"
        " OR lower(suggested_label)=?) ORDER BY pinned DESC, updated_at DESC LIMIT 1",
        (key_or_id, key_or_id, key_or_id.lower(), key_or_id.lower()))
    if r:
        return r["id"]
    seen = set()
    cur = key_or_id
    while cur not in seen:
        seen.add(cur)
        a = repo.query_one("SELECT new_id FROM collection_aliases WHERE old_id=? ORDER BY created_at DESC LIMIT 1",
                           (cur,))
        if a is None:
            return None
        live = repo.query_one("SELECT id FROM collections WHERE id=? AND retired_at IS NULL", (a["new_id"],))
        if live:
            return live["id"]
        cur = a["new_id"]
    return None


def collection_members_for_filter(repo: Repository, key_or_id: str) -> set[str]:
    cid = resolve_collection_id(repo, key_or_id)
    if cid is None:
        from services.search.service import SearchError

        raise SearchError(f"collection:{key_or_id} not found")
    return {r["asset_id"] for r in repo.query(
        "SELECT asset_id FROM memberships WHERE collection_id=? AND state!='excluded'", (cid,))}


# ---------------------------------------------------------------------------
# Correction commands (M6)
# ---------------------------------------------------------------------------

import json  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402

from models.collections import Collection, CorrectionCommand, CorrectionResult, Membership  # noqa: E402
from services.analyze.catalog import catalog  # noqa: E402
from services.library.repository import StaleRevisionError  # noqa: E402


class CorrectionError(ValueError):
    pass


def _record(c, actor: str, target_type: str, target_id: str, field: str, prev, new, scope: str, reason: str,
            revision: int) -> str:
    cid = f"cor_{uuid.uuid4().hex[:16]}"
    c.execute("INSERT INTO corrections(id, actor, at, target_type, target_id, field, previous, new, scope, reason,"
              " revision) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (cid, actor, time.time(), target_type, target_id, field, json.dumps(prev, sort_keys=True),
               json.dumps(new, sort_keys=True), scope, reason, revision))
    return cid


def _live(c, cid: str):
    r = c.execute("SELECT * FROM collections WHERE id=? AND retired_at IS NULL", (cid,)).fetchone()
    if r is None:
        raise CorrectionError(f"collection {cid} not found")
    return r


def _check_rev(row, expected: int | None) -> None:
    if expected is not None and row["revision"] != expected:
        raise StaleRevisionError(f"collection {row['id']} changed (revision {row['revision']} != {expected})")


def _bump(c, cid: str) -> int:
    c.execute("UPDATE collections SET revision=revision+1, updated_at=? WHERE id=?", (time.time(), cid))
    return c.execute("SELECT revision FROM collections WHERE id=?", (cid,)).fetchone()[0]


def _set_state(c, cid: str, aid: str, state: str, method: str = "user") -> None:
    c.execute("INSERT INTO memberships(collection_id, asset_id, method, affinity, affinity_kind, evidence, state,"
              " updated_at) VALUES (?,?,?,NULL,'user','{}',?,?) ON CONFLICT(collection_id, asset_id) DO UPDATE SET"
              " state=excluded.state, updated_at=excluded.updated_at", (cid, aid, method, state, time.time()))


def apply_correction(repo: Repository, library_id: str, cmd: CorrectionCommand, expected_revision: int | None = None,
                     actor: str = "local-user") -> CorrectionResult:
    """Apply one user correction atomically. User state always outranks machine suggestions."""
    ids: list[str] = []
    affected: list[str] = list(cmd.asset_ids)
    with repo.write() as c:
        if cmd.op == "rename":
            row = _live(c, cmd.collection_id)
            _check_rev(row, expected_revision)
            label = (cmd.label or "").strip()[:120] or None
            c.execute("UPDATE collections SET user_label=? WHERE id=?", (label, row["id"]))
            rev = _bump(c, row["id"])
            ids.append(_record(c, actor, "collection", row["id"], "user_label", row["user_label"], label,
                               "collection", cmd.reason, rev))
            target = row["id"]
        elif cmd.op in {"pin", "hide"}:
            row = _live(c, cmd.collection_id)
            _check_rev(row, expected_revision)
            col = "pinned" if cmd.op == "pin" else "hidden"
            val = 1 if cmd.value in (True, "true", "1", 1) else 0
            c.execute(f"UPDATE collections SET {col}=? WHERE id=?", (val, row["id"]))
            rev = _bump(c, row["id"])
            ids.append(_record(c, actor, "collection", row["id"], col, bool(row[col]), bool(val), "collection",
                               cmd.reason, rev))
            target = row["id"]
        elif cmd.op in {"confirm", "exclude"}:
            row = _live(c, cmd.collection_id)
            _check_rev(row, expected_revision)
            state = "confirmed" if cmd.op == "confirm" else "excluded"
            for aid in cmd.asset_ids:
                prev = c.execute("SELECT state FROM memberships WHERE collection_id=? AND asset_id=?",
                                 (row["id"], aid)).fetchone()
                _set_state(c, row["id"], aid, state)
                ids.append(_record(c, actor, "membership", f"{row['id']}:{aid}", "state",
                                   prev["state"] if prev else None, state, "collection", cmd.reason,
                                   row["revision"] + 1))
            rev = _bump(c, row["id"])
            target = row["id"]
        elif cmd.op == "move":
            src, dst = _live(c, cmd.collection_id), _live(c, cmd.to)
            _check_rev(dst, expected_revision)
            for aid in cmd.asset_ids:
                _set_state(c, src["id"], aid, "excluded")
                _set_state(c, dst["id"], aid, "confirmed")
                ids.append(_record(c, actor, "membership", aid, "moved", src["id"], dst["id"], "collection",
                                   cmd.reason, dst["revision"] + 1))
            _bump(c, src["id"])
            rev = _bump(c, dst["id"])
            target = dst["id"]
        elif cmd.op == "merge":
            into = _live(c, cmd.into)
            _check_rev(into, expected_revision)
            for other in cmd.collection_ids:
                if other == into["id"]:
                    continue
                o = _live(c, other)
                if o["ctype"] != into["ctype"]:
                    raise CorrectionError("only groups of the same type can be merged")
                for m in c.execute("SELECT asset_id, state FROM memberships WHERE collection_id=?", (o["id"],)).fetchall():
                    if m["state"] != "excluded":
                        _set_state(c, into["id"], m["asset_id"], "confirmed")
                        affected.append(m["asset_id"])
                c.execute("UPDATE collections SET retired_at=?, updated_at=? WHERE id=?", (time.time(), time.time(), o["id"]))
                c.execute("INSERT OR IGNORE INTO collection_aliases(old_id, new_id, reason, created_at) VALUES (?,?,?,?)",
                          (o["id"], into["id"], "merged", time.time()))
                ids.append(_record(c, actor, "collection", o["id"], "merged_into", None, into["id"], "collection",
                                   cmd.reason, into["revision"] + 1))
            rev = _bump(c, into["id"])
            target = into["id"]
        elif cmd.op == "split":
            src = _live(c, cmd.collection_id)
            _check_rev(src, expected_revision)
            if not cmd.asset_ids:
                raise CorrectionError("split needs the assets that form the new group")
            new_id = f"col_{src['ctype'][:3]}_{uuid.uuid4().hex[:12]}"
            now = time.time()
            c.execute("INSERT INTO collections(id, library_id, ctype, key, parent_id, suggested_label, user_label, rule,"
                      " representative_asset, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (new_id, library_id, src["ctype"], None, src["parent_id"], f"Split of {src['suggested_label']}",
                       (cmd.label or "").strip() or None, json.dumps({"split_from": src["id"]}), cmd.asset_ids[0],
                       now, now))
            for aid in cmd.asset_ids:
                _set_state(c, src["id"], aid, "excluded")
                _set_state(c, new_id, aid, "confirmed")
            c.execute("INSERT OR IGNORE INTO collection_aliases(old_id, new_id, reason, created_at) VALUES (?,?,?,?)",
                      (src["id"], new_id, "split", now))
            _bump(c, src["id"])
            ids.append(_record(c, actor, "collection", src["id"], "split", None,
                               {"new": new_id, "assets": cmd.asset_ids}, "collection", cmd.reason, src["revision"] + 1))
            rev = 0
            target = new_id
        elif cmd.op == "create":
            new_id = f"col_user_{uuid.uuid4().hex[:12]}"
            now = time.time()
            label = (cmd.label or "My collection").strip()[:120]
            c.execute("INSERT INTO collections(id, library_id, ctype, key, suggested_label, user_label, rule,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (new_id, library_id, "user", None, label, label, "{}", now, now))
            for aid in cmd.asset_ids:
                _set_state(c, new_id, aid, "confirmed")
            ids.append(_record(c, actor, "collection", new_id, "created", None, {"label": label, "assets": cmd.asset_ids},
                               "collection", cmd.reason, 0))
            rev = 0
            target = new_id
        elif cmd.op in {"set_decision", "clear_decision"}:
            q = catalog()["questions"].get(cmd.question_id or "")
            if q is None or not cmd.asset_id:
                raise CorrectionError("set_decision needs a known question_id and an asset_id")
            prev = c.execute("SELECT value FROM metadata_overrides WHERE asset_id=? AND question_id=?",
                             (cmd.asset_id, cmd.question_id)).fetchone()
            if cmd.op == "set_decision":
                allowed = set(q["options"]) if q["type"] == "choice" else {"yes", "no"}
                value = str(cmd.value)
                if value not in allowed:
                    raise CorrectionError(f"{cmd.question_id} accepts {sorted(allowed)}")
                cor = _record(c, actor, "asset", cmd.asset_id, cmd.question_id, prev["value"] if prev else None,
                              value, "asset", cmd.reason, 0)
                c.execute("INSERT INTO metadata_overrides(asset_id, question_id, value, correction_id, updated_at)"
                          " VALUES (?,?,?,?,?) ON CONFLICT(asset_id, question_id) DO UPDATE SET value=excluded.value,"
                          " correction_id=excluded.correction_id, updated_at=excluded.updated_at",
                          (cmd.asset_id, cmd.question_id, value, cor, time.time()))
            else:
                cor = _record(c, actor, "asset", cmd.asset_id, cmd.question_id, prev["value"] if prev else None,
                              None, "asset", cmd.reason, 0)
                c.execute("DELETE FROM metadata_overrides WHERE asset_id=? AND question_id=?",
                          (cmd.asset_id, cmd.question_id))
            ids.append(cor)
            affected = [cmd.asset_id]
            rev = None
            target = None
        else:  # pragma: no cover - pydantic restricts ops
            raise CorrectionError(f"unsupported op {cmd.op}")
    if cmd.op in {"set_decision", "clear_decision"}:
        from services.organize.collections import refresh_smart_memberships

        refresh_smart_memberships(repo, library_id, affected)
    return CorrectionResult(ok=True, correction_ids=ids, collection_id=target, new_revision=rev,
                            affected_assets=sorted(set(affected)))


def list_collections(repo: Repository, library_id: str, ctype: str | None = None, parent_id: str | None = None,
                     include_hidden: bool = False, with_members: bool = False) -> list[Collection]:
    sql = ("SELECT c.*, (SELECT COUNT(*) FROM memberships m JOIN assets a ON a.id=m.asset_id WHERE"
           " m.collection_id=c.id AND m.state!='excluded' AND a.deleted_at IS NULL) AS n FROM collections c"
           " WHERE c.library_id=? AND c.retired_at IS NULL")
    params: list = [library_id]
    if ctype:
        sql += " AND c.ctype=?"
        params.append(ctype)
    if parent_id:
        sql += " AND c.parent_id=?"
        params.append(parent_id)
    if not include_hidden:
        sql += " AND c.hidden=0"
    sql += " ORDER BY c.pinned DESC, c.ctype, COALESCE(c.user_label, c.suggested_label)"
    out = []
    for r in repo.query(sql, tuple(params)):
        members = []
        if with_members:
            members = [Membership(asset_id=m["asset_id"], method=m["method"], affinity=m["affinity"],
                                  affinity_kind=m["affinity_kind"], state=m["state"], evidence=json.loads(m["evidence"]))
                       for m in repo.query("SELECT m.* FROM memberships m JOIN assets a ON a.id=m.asset_id WHERE"
                                           " m.collection_id=? AND a.deleted_at IS NULL ORDER BY m.state, m.affinity DESC,"
                                           " m.asset_id", (r["id"],))]
        out.append(Collection(id=r["id"], ctype=r["ctype"], key=r["key"], parent_id=r["parent_id"],
                              label=r["user_label"] or r["suggested_label"], suggested_label=r["suggested_label"],
                              user_label=r["user_label"], pinned=bool(r["pinned"]), hidden=bool(r["hidden"]),
                              representative_asset=r["representative_asset"], revision=r["revision"],
                              member_count=r["n"], members=members))
    return out
