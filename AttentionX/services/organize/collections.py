"""Smart context collections: evidence-backed sets over typed decisions.

Not clustering. Each collection is a rule over decisions (or user overrides)
with a validation-selected threshold (initially 0.80 for high-trust sets, per
catalog ``collection_threshold``). Membership is multi-valued: a film frame
shared in a LinkedIn post can be in both sets. Assets without a confident
capture/context decision land in "Needs review", never forced anywhere.

Membership states: ``suggested`` (machine), ``confirmed`` / ``excluded``
(user). Refreshes only add/update/remove *suggested* rows, so user decisions
survive re-analysis and re-runs.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from services.analyze.catalog import decision_threshold
from services.library.repository import Repository

TAXONOMY_VERSION = "smart-collections/1.1"


@dataclass(frozen=True)
class SmartRule:
    key: str
    label: str
    parent: str | None
    test: Callable[[dict], tuple[bool, float | None, dict]]   # decisions view -> (member, affinity, evidence)


def _choice(q: str, value: str):
    def t(dv: dict):
        d = dv.get(q)
        if d is None:
            return False, None, {}
        if d["source"] == "user":
            return d["value"] == value, None, {q: f"{d['value']} (your correction)"}
        if d["status"] != "complete" or d["value"] != value:
            return False, None, {}
        p = d["probs"].get(value, 0.0)
        return p >= decision_threshold(q, value), p, {q: {"value": value, "p": round(p, 4)}}
    return t


def _noul(q: str):
    def t(dv: dict):
        d = dv.get(q)
        if d is None:
            return False, None, {}
        if d["source"] == "user":
            return d["value"] == "yes", None, {q: f"{d['value']} (your correction)"}
        if d["status"] != "complete":
            return False, None, {}
        p = float(d["value"])
        return p >= decision_threshold(q), p, {q: {"p_yes": round(p, 4)}}
    return t


def _all(*tests):
    def t(dv):
        ok, aff, ev = True, None, {}
        for x in tests:
            o, a, e = x(dv)
            ok &= o
            ev.update(e)
            if a is not None:
                aff = a if aff is None else min(aff, a)
        return ok, aff, ev
    return t


def _any(*tests):
    def t(dv):
        best = (False, None, {})
        for x in tests:
            o, a, e = x(dv)
            if o and (not best[0] or (a or 0) > (best[1] or 0)):
                best = (o, a, e)
        return best
    return t


def _not(test):
    def t(dv):
        o, _, _ = test(dv)
        return (not o), None, {}
    return t


_linkedin = _choice("source_app", "linkedin")
_jobs = _any(_noul("context.job_posting"), _noul("topic.hiring"))
_tech = _any(_noul("topic.ai_ml"), _noul("topic.software_development"))


def _is_video(dv: dict):
    if dv.get("_kind") == "video":
        return True, None, {"asset_kind": "video"}
    return False, None, {}


def _needs_review(dv: dict):
    if dv.get("_kind") == "video":
        return False, None, {}  # image context questions are not asked of videos
    cap = dv.get("capture_type")
    if cap is None:
        return True, None, {"capture_type": "not decided"}
    if cap["source"] == "user":
        return False, None, {}
    if cap["status"] != "complete":
        return True, None, {"capture_type": cap["status"]}
    return False, None, {}


SMART_RULES: list[SmartRule] = [
    SmartRule("linkedin_screenshots", "LinkedIn screenshots", None, _linkedin),
    SmartRule("linkedin_job_posts", "LinkedIn · job posts", "linkedin_screenshots", _all(_linkedin, _jobs)),
    SmartRule("linkedin_technical_posts", "LinkedIn · technical posts", "linkedin_screenshots",
              _all(_linkedin, _tech, _not(_jobs))),
    SmartRule("linkedin_general_posts", "LinkedIn · general posts", "linkedin_screenshots",
              _all(_linkedin, _not(_jobs), _not(_tech))),
    SmartRule("movie_tv_frames", "Movie / TV frames", None, _noul("context.film_tv_frame")),
    SmartRule("source_code", "Code screenshots", None, _noul("context.source_code")),
    SmartRule("presentation_slides", "Presentation slides", None, _noul("context.presentation_slide")),
    SmartRule("documents", "Documents & articles", None,
              _any(_choice("capture_type", "scanned_document"), _noul("context.article"))),
    SmartRule("conversations", "Conversations", None, _noul("context.conversation")),
    SmartRule("screenshots", "All screenshots", None, _choice("capture_type", "screenshot")),
    SmartRule("photos", "Photos", None, _choice("capture_type", "photo")),
    SmartRule("videos", "Videos", None, _is_video),
    SmartRule("needs_review", "Needs review (unclassified)", None, _needs_review),
]
RULES_BY_KEY = {r.key: r for r in SMART_RULES}


def smart_collection_id(library_id: str, key: str) -> str:
    return f"col_smart_{library_id}_{key}"


def ensure_smart_collections(repo: Repository, library_id: str) -> None:
    now = time.time()
    with repo.write() as c:
        for r in SMART_RULES:
            cid = smart_collection_id(library_id, r.key)
            c.execute(
                "INSERT OR IGNORE INTO collections(id, library_id, ctype, key, parent_id, suggested_label, rule,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, library_id, "smart", r.key, smart_collection_id(library_id, r.parent) if r.parent else None,
                 r.label, json.dumps({"taxonomy": TAXONOMY_VERSION, "key": r.key}), now, now))


def decisions_view(repo: Repository, asset_id: str) -> dict:
    """Effective decisions: user overrides win over machine output."""
    dv: dict[str, dict] = {}
    for r in repo.query("SELECT question_id, dtype, value, p_value, probs, status FROM decisions WHERE asset_id=?",
                        (asset_id,)):
        value = r["value"]
        if r["dtype"] == "noul" and value is not None:
            value = float(value)
        dv[r["question_id"]] = {"source": "machine", "status": r["status"], "value": value,
                                "probs": json.loads(r["probs"]), "dtype": r["dtype"]}
    for r in repo.query("SELECT question_id, value FROM metadata_overrides WHERE asset_id=?", (asset_id,)):
        dv[r["question_id"]] = {"source": "user", "status": "complete", "value": r["value"]}
    return dv


def refresh_smart_memberships(repo: Repository, library_id: str, asset_ids: list[str]) -> dict:
    ensure_smart_collections(repo, library_id)
    added = removed = 0
    now = time.time()
    for aid in asset_ids:
        alive = repo.query_one("SELECT deleted_at, metadata_revision, kind FROM assets WHERE id=?", (aid,))
        dv = decisions_view(repo, aid) if alive and alive["deleted_at"] is None and alive["metadata_revision"] else None
        if dv is not None:
            dv["_kind"] = alive["kind"]
        with repo.write() as c:
            for r in SMART_RULES:
                cid = smart_collection_id(library_id, r.key)
                existing = c.execute("SELECT state FROM memberships WHERE collection_id=? AND asset_id=?",
                                     (cid, aid)).fetchone()
                if existing and existing["state"] in {"confirmed", "excluded"}:
                    continue  # user decision is authoritative
                member, aff, ev = (r.test(dv) if dv is not None else (False, None, {}))
                if member:
                    method = "user_override" if any("your correction" in str(v) for v in ev.values()) else "decision"
                    c.execute(
                        "INSERT INTO memberships(collection_id, asset_id, method, affinity, affinity_kind, evidence,"
                        " state, updated_at) VALUES (?,?,?,?,?,?,'suggested',?) ON CONFLICT(collection_id, asset_id)"
                        " DO UPDATE SET method=excluded.method, affinity=excluded.affinity, evidence=excluded.evidence,"
                        " updated_at=excluded.updated_at",
                        (cid, aid, method, aff, "zero_shot_softmax_uncalibrated" if aff is not None else "rule",
                         json.dumps(ev, sort_keys=True), now))
                    added += existing is None
                elif existing:
                    c.execute("DELETE FROM memberships WHERE collection_id=? AND asset_id=?", (cid, aid))
                    removed += 1
    return {"added": added, "removed": removed}
