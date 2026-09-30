"""Visual/topic similarity groups inside smart-collection scopes.

Per scope, one channel (never an arithmetic mix of vector spaces):
- image scopes (photos, movie/TV frames): CLIP global vectors;
- text-heavy scopes (LinkedIn, code, documents, slides, conversations): the
  mean of the asset's MiniLM OCR-chunk vectors, so shared UI chrome does not
  dominate grouping.

Algorithm (no N x N matrix, no forced K):
1. blockwise top-k neighbours; keep *mutual* neighbours with sim >= tau_edge;
2. process edges by descending similarity and merge two groups only if the
   *minimum* pairwise similarity across them is >= tau_link (complete
   linkage) — A~B and B~C does not pull A and C together unless A~C;
3. groups smaller than min_size stay unclustered (singletons/noise are fine).
Affinity is the cosine to the group's medoid, labelled as such — it is not
a calibrated probability. Parameters are tuned on the dev split
(reports/evaluation.md).
"""
from __future__ import annotations

import json
import time
import uuid
from collections import Counter

import numpy as np

from services.library.repository import Repository
from services.organize.collections import RULES_BY_KEY, smart_collection_id

SCOPES = {
    "photos": "image",
    "movie_tv_frames": "image",
    "linkedin_screenshots": "text",
    "source_code": "text",
    "documents": "text",
    "presentation_slides": "text",
    "conversations": "text",
}
PARAMS = {  # dev-split tuned (reports/tuning_dev.json)
    "image": {"k": 8, "tau_edge": 0.75, "tau_link": 0.65, "min_size": 2, "max_size": 300},
    "text": {"k": 8, "tau_edge": 0.80, "tau_link": 0.70, "min_size": 2, "max_size": 300},
}
METHOD_VERSION = "mutual-knn+complete-link/1"


def scope_vectors(repo: Repository, scope_key: str, library_id: str) -> tuple[list[str], np.ndarray]:
    from services.analyze.vectors_registry import active_namespace

    cid = smart_collection_id(library_id, scope_key)
    members = [r["asset_id"] for r in repo.query(
        "SELECT m.asset_id FROM memberships m JOIN assets a ON a.id=m.asset_id WHERE m.collection_id=?"
        " AND m.state!='excluded' AND a.deleted_at IS NULL ORDER BY m.asset_id", (cid,))]
    if not members:
        return [], np.zeros((0, 1), np.float32)
    kind = SCOPES[scope_key]
    ns = active_namespace(repo, "image" if kind == "image" else "ocr_text")
    if ns is None:
        return [], np.zeros((0, 1), np.float32)
    vecs: dict[str, list[np.ndarray]] = {}
    for i in range(0, len(members), 500):
        chunk = members[i:i + 500]
        view_filter = " AND view_id='global'" if kind == "image" else ""
        for r in repo.query(f"SELECT asset_id, vector FROM vectors WHERE namespace=?{view_filter} AND asset_id IN"
                            f" ({','.join('?' * len(chunk))})", (ns["namespace"], *chunk)):
            vecs.setdefault(r["asset_id"], []).append(np.frombuffer(r["vector"], dtype=np.float32))
    if kind == "text":
        # Prefer the UI-chrome-free body vector; fall back to the mean of chunks.
        body = {}
        for i in range(0, len(members), 500):
            chunk = members[i:i + 500]
            for r in repo.query(f"SELECT asset_id, vector FROM vectors WHERE namespace=? AND view_id='body' AND"
                                f" asset_id IN ({','.join('?' * len(chunk))})", (ns["namespace"], *chunk)):
                body[r["asset_id"]] = [np.frombuffer(r["vector"], dtype=np.float32)]
        vecs.update(body)
    ids = [a for a in members if a in vecs]
    if not ids:
        return [], np.zeros((0, 1), np.float32)
    X = np.stack([np.mean(vecs[a], axis=0) for a in ids]).astype(np.float32)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    return ids, X


def cluster(X: np.ndarray, p: dict) -> list[list[int]]:
    n = X.shape[0]
    if n < 2:
        return []
    k = min(p["k"], n - 1)
    nbrs: list[set[int]] = []
    edge_sims: dict[tuple[int, int], float] = {}
    for s in range(0, n, 1024):
        S = X[s:s + 1024] @ X.T
        for r in range(S.shape[0]):
            i = s + r
            S[r, i] = -1.0
            top = np.argpartition(-S[r], k - 1)[:k] if k < n else np.arange(n)
            nb = {int(j) for j in top if S[r, j] >= p["tau_edge"]}
            nbrs.append(nb)
            for j in nb:
                edge_sims[(min(i, j), max(i, j))] = float(S[r, j])
    edges = sorted(((s, i, j) for (i, j), s in edge_sims.items() if j in nbrs[i] and i in nbrs[j]), reverse=True)
    parent = list(range(n))
    members = {i: [i] for i in range(n)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, i, j in edges:
        a, b = find(i), find(j)
        if a == b or len(members[a]) + len(members[b]) > p["max_size"]:
            continue
        if float((X[members[a]] @ X[members[b]].T).min()) < p["tau_link"]:
            continue
        parent[b] = a
        members[a] += members.pop(b)
    return [sorted(m) for m in members.values() if len(m) >= p["min_size"]]


def medoid(X: np.ndarray, idx: list[int]) -> int:
    S = X[idx] @ X[idx].T
    return idx[int(np.argmax(S.sum(1)))]


def suggest_label(repo: Repository, scope_key: str, asset_ids: list[str], n: int) -> str:
    """Closed vocabulary only: majority detected object / decided topic or scene."""
    votes: Counter = Counter()
    for aid in asset_ids:
        seen = set()
        for r in repo.query("SELECT label FROM object_observations WHERE asset_id=? AND score>=0.5", (aid,)):
            seen.add(("object", r["label"]))
        for r in repo.query("SELECT question_id, p_value FROM decisions WHERE asset_id=? AND dtype='noul' AND"
                            " status='complete' AND (question_id LIKE 'topic.%' OR question_id LIKE 'scene.%')", (aid,)):
            if (r["p_value"] or 0) >= 0.5:
                seen.add(("decision", r["question_id"].split(".", 1)[1].replace("_", " ")))
        votes.update(seen)
    scope_label = RULES_BY_KEY[scope_key].label
    if votes:
        (kind, label), count = votes.most_common(1)[0]
        if count >= max(2, (len(asset_ids) + 1) // 2):
            return f"{scope_label} · {label}"
    return f"{scope_label} · similar group {n}"


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


def rebuild_scope(repo: Repository, library_id: str, scope_key: str, params: dict | None = None) -> dict:
    kind = SCOPES[scope_key]
    p = dict(PARAMS[kind], **(params or {}))
    ids, X = scope_vectors(repo, scope_key, library_id)
    groups_idx = cluster(X, p) if len(ids) >= 2 else []
    parent_id = smart_collection_id(library_id, scope_key)
    now = time.time()
    snap = f"snap_{uuid.uuid4().hex[:12]}"

    old = {}
    for r in repo.query("SELECT id, pinned, user_label, representative_asset FROM collections WHERE ctype='similarity'"
                        " AND parent_id=? AND retired_at IS NULL", (parent_id,)):
        mem = {m["asset_id"] for m in repo.query(
            "SELECT asset_id FROM memberships WHERE collection_id=? AND state!='excluded'", (r["id"],))}
        conf = {m["asset_id"] for m in repo.query(
            "SELECT asset_id FROM memberships WHERE collection_id=? AND state='confirmed'", (r["id"],))}
        excl = {m["asset_id"] for m in repo.query(
            "SELECT asset_id FROM memberships WHERE collection_id=? AND state='excluded'", (r["id"],))}
        old[r["id"]] = {"members": mem, "confirmed": conf, "excluded": excl, "pinned": bool(r["pinned"]),
                        "user_label": r["user_label"]}

    new_groups = []
    for g in groups_idx:
        m = medoid(X, g)
        sims = X[g] @ X[m]
        new_groups.append({"members": [ids[i] for i in g], "rep": ids[m],
                           "affinity": {ids[i]: float(s) for i, s in zip(g, sims)}})

    # Pinned groups are frozen: their members are not reassigned by the algorithm.
    frozen = {a for gid, o in old.items() if o["pinned"] for a in o["members"]}
    for ng in new_groups:
        ng["members"] = [a for a in ng["members"] if a not in frozen]
    new_groups = [g for g in new_groups if len(g["members"]) >= p["min_size"]]

    # Reconcile ids: best-overlap old group keeps its id (split -> others new).
    assigned: dict[int, str] = {}
    taken: set[str] = set()
    pairs = sorted(((_overlap(set(ng["members"]), o["members"]), gi, oid)
                    for gi, ng in enumerate(new_groups) for oid, o in old.items() if not o["pinned"]), reverse=True)
    for ov, gi, oid in pairs:
        if ov >= 0.3 and gi not in assigned and oid not in taken:
            assigned[gi] = oid
            taken.add(oid)

    confirmed_in = {a: oid for oid, o in old.items() for a in o["confirmed"]}
    aliases = []
    with repo.write() as c:
        c.execute("INSERT INTO cluster_snapshots(id, library_id, kind, method, params, stats, created_at)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (snap, library_id, f"similarity:{scope_key}", METHOD_VERSION, json.dumps(p, sort_keys=True),
                   json.dumps({"assets": len(ids), "groups": len(new_groups),
                               "grouped": sum(len(g["members"]) for g in new_groups)}), now))
        live_ids = set()
        for gi, ng in enumerate(new_groups):
            gid = assigned.get(gi) or f"col_sim_{uuid.uuid4().hex[:12]}"
            live_ids.add(gid)
            label = suggest_label(repo, scope_key, ng["members"], gi + 1)
            if gid in old:
                c.execute("UPDATE collections SET suggested_label=?, representative_asset=?, snapshot_id=?, updated_at=?,"
                          " revision=revision+1 WHERE id=?", (label, ng["rep"], snap, now, gid))
            else:
                c.execute("INSERT INTO collections(id, library_id, ctype, key, parent_id, suggested_label, rule,"
                          " representative_asset, snapshot_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (gid, library_id, "similarity", None, parent_id, label,
                           json.dumps({"scope": scope_key, "channel": kind, "method": METHOD_VERSION}),
                           ng["rep"], snap, now, now))
                # Record lineage from any old group this one overlaps (split/merge history).
                for oid, o in old.items():
                    if oid not in taken and _overlap(set(ng["members"]), o["members"]) > 0:
                        aliases.append((oid, gid, "recluster"))
            excluded = old.get(gid, {}).get("excluded", set())
            c.execute("DELETE FROM memberships WHERE collection_id=? AND state='suggested'", (gid,))
            for aid in ng["members"]:
                if aid in excluded or confirmed_in.get(aid, gid) != gid:
                    continue  # user exclusions and user placements win
                c.execute(
                    "INSERT INTO memberships(collection_id, asset_id, method, affinity, affinity_kind, evidence, state,"
                    " snapshot_id, updated_at) VALUES (?,?,?,?,?,?,'suggested',?,?)"
                    " ON CONFLICT(collection_id, asset_id) DO UPDATE SET affinity=excluded.affinity,"
                    " snapshot_id=excluded.snapshot_id, updated_at=excluded.updated_at",
                    (gid, aid, "cluster", ng["affinity"][aid], "cosine_to_medoid",
                     json.dumps({"scope": scope_key, "channel": kind, "medoid": ng["rep"]}), snap, now))
        # Old groups not matched: keep if user-owned (pinned/renamed/confirmed), else retire.
        for oid, o in old.items():
            if oid in live_ids:
                continue
            if o["pinned"] or o["user_label"] or o["confirmed"]:
                c.execute("DELETE FROM memberships WHERE collection_id=? AND state='suggested'", (oid,))
                continue
            c.execute("UPDATE collections SET retired_at=?, updated_at=? WHERE id=?", (now, now, oid))
            c.execute("DELETE FROM memberships WHERE collection_id=? AND state='suggested'", (oid,))
        for old_id, new_id, reason in aliases:
            c.execute("INSERT OR IGNORE INTO collection_aliases(old_id, new_id, reason, created_at) VALUES (?,?,?,?)",
                      (old_id, new_id, reason, now))
    return {"scope": scope_key, "snapshot": snap, "assets": len(ids), "groups": len(new_groups),
            "grouped": sum(len(g["members"]) for g in new_groups)}


def assign_incremental(repo: Repository, library_id: str, asset_id: str) -> list[str]:
    """Attach one new/changed asset to an existing group when it is coherent with
    *every* member (min sim >= tau_link) and close to one (max >= tau_edge).
    Otherwise it stays unclustered until the next rebuild. O(group members)."""
    joined = []
    for scope_key, kind in SCOPES.items():
        parent_id = smart_collection_id(library_id, scope_key)
        in_scope = repo.query_one("SELECT 1 FROM memberships WHERE collection_id=? AND asset_id=? AND state!='excluded'",
                                  (parent_id, asset_id))
        if not in_scope:
            continue
        already = repo.query_one(
            "SELECT 1 FROM memberships m JOIN collections c ON c.id=m.collection_id WHERE c.parent_id=? AND"
            " c.ctype='similarity' AND c.retired_at IS NULL AND m.asset_id=?", (parent_id, asset_id))
        if already:
            continue
        ids, X = scope_vectors(repo, scope_key, library_id)
        if asset_id not in ids:
            continue
        pos = {a: i for i, a in enumerate(ids)}
        x = X[pos[asset_id]]
        p = PARAMS[kind]
        best = None
        for g in repo.query("SELECT id, representative_asset FROM collections WHERE ctype='similarity' AND parent_id=?"
                            " AND retired_at IS NULL AND pinned=0", (parent_id,)):
            mem = [r["asset_id"] for r in repo.query(
                "SELECT asset_id FROM memberships WHERE collection_id=? AND state!='excluded'", (g["id"],))]
            idx = [pos[a] for a in mem if a in pos]
            if not idx:
                continue
            sims = X[idx] @ x
            if sims.min() >= p["tau_link"] and sims.max() >= p["tau_edge"]:
                rep_sim = float(X[pos[g["representative_asset"]]] @ x) if g["representative_asset"] in pos else float(sims.mean())
                if best is None or sims.mean() > best[1]:
                    best = (g["id"], float(sims.mean()), rep_sim)
        if best:
            with repo.write() as c:
                c.execute("INSERT OR IGNORE INTO memberships(collection_id, asset_id, method, affinity, affinity_kind,"
                          " evidence, state, updated_at) VALUES (?,?,?,?,?,?,'suggested',?)",
                          (best[0], asset_id, "incremental", best[2], "cosine_to_medoid",
                           json.dumps({"scope": scope_key, "channel": kind, "mean_member_cos": round(best[1], 4)}),
                           time.time()))
            joined.append(best[0])
    return joined
