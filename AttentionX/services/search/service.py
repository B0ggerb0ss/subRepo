"""search_library / find_similar use cases.

Order of operations (docs/architecture-decisions/ADR-004-retrieval.md):
1. parse -> typed hard filters (AND) + literal phrases + free-text intent;
2. eligibility: library, not deleted, analyzed, then every hard filter;
3. channels retrieve independently inside the eligible set:
   lexical OCR (bm25), user annotations (bm25), OCR-text semantic (MiniLM
   cosine), image-text semantic (CLIP cosine); region/chunk hits are
   collapsed to one candidate per asset *before* fusion;
4. reciprocal-rank fusion  sum_c w_c / (k + rank_c)  (no raw score mixing);
5. evidence rendered only from stored observations.
Unavailable channels are reported in ``degraded``; nothing is fabricated.
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from datetime import date, datetime

from models.search import (
    Filter,
    MatchEvidence,
    ParsedQuery,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from services.analyze.catalog import (
    FILTER_QUESTION,
    catalog,
    object_labels,
    resolve_object_label,
)
from services.library.config import LibraryConfig
from services.library.repository import Repository
from services.search import lexical
from services.search.parser import QueryParseError, parse_query

RRF_K = 60.0
DEFAULT_WEIGHTS = {"phrase": 1.0, "lexical": 1.0, "annotation": 1.0, "ocr_semantic": 1.0, "visual": 1.0}


class SearchError(ValueError):
    pass


class SearchService:
    def __init__(self, repo: Repository, cfg: LibraryConfig, weights: dict | None = None, rrf_k: float = RRF_K):
        self.repo = repo
        self.cfg = cfg
        self.weights = dict(DEFAULT_WEIGHTS, **(weights or {}))
        self.rrf_k = rrf_k
        self._cache: OrderedDict = OrderedDict()

    # ------------------------------------------------------------------
    def state_token(self) -> tuple:
        r = self.repo.query_one(
            "SELECT (SELECT COALESCE(MAX(created_at),0) FROM metadata_revisions) m,"
            " (SELECT COUNT(*) FROM assets WHERE deleted_at IS NOT NULL) d,"
            " (SELECT COALESCE(MAX(updated_at),0) FROM user_annotations) a,"
            " (SELECT COALESCE(MAX(updated_at),0) FROM memberships) ms,"
            " (SELECT COALESCE(MAX(updated_at),0) FROM metadata_overrides) o,"
            " (SELECT COALESCE(SUM(revision),0) FROM vector_namespaces) v")
        return tuple(r)

    def index_revision(self) -> dict[str, int]:
        rows = self.repo.query("SELECT namespace, revision FROM vector_namespaces WHERE state='active'")
        out = {r["namespace"]: r["revision"] for r in rows}
        out["metadata_revisions"] = self.repo.query_one("SELECT COUNT(*) n FROM metadata_revisions")["n"]
        return out

    # ------------------------------------------------------------------
    def search(self, req: SearchRequest) -> SearchResponse:
        t0 = time.perf_counter()
        try:
            pq = parse_query(req.query)
        except QueryParseError as e:
            raise SearchError(str(e)) from e
        key = (req.model_dump_json(), self.state_token())
        if key in self._cache:
            resp = self._cache[key].model_copy(deep=True)
            resp.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            return resp

        eligible, filter_ev = self._eligible(pq, req.library_id)
        degraded: list[str] = list(pq.approximate_notes)
        channels_used: list[str] = []
        ranked: dict[str, list[tuple[str, float]]] = {}
        evidence: dict[str, list[MatchEvidence]] = {}

        # Literal phrases: hard constraints (AND) + ranking by occurrences.
        for phrase in pq.text_phrases:
            hits = lexical.phrase_search(self.repo, phrase, eligible)
            eligible = eligible & set(hits)
            for aid, matches in hits.items():
                for m in matches:
                    evidence.setdefault(aid, []).append(MatchEvidence(
                        reason="OCR_PHRASE", detail=f'OCR text contains "{phrase}"',
                        region_ids=m["region_ids"], polygons=m["polygons"], excerpt=m["excerpt"],
                        score_kind="literal_match"))
            channels_used.append("phrase")
        if pq.text_phrases:
            occ = {aid: sum(1 for e in evidence.get(aid, []) if e.reason == "OCR_PHRASE") for aid in eligible}
            ranked["phrase"] = sorted(occ.items(), key=lambda kv: (-kv[1], kv[0]))

        similar_ref = req.similar_to
        if pq.free_text and "lexical" in req.channels:
            res = lexical.word_search(self.repo, pq.free_text, eligible)
            ranked["lexical"] = [(aid, s) for aid, s, _ in res]
            for aid, s, ev in res:
                if ev:
                    evidence.setdefault(aid, []).append(MatchEvidence(
                        reason="OCR_LEXICAL",
                        detail="OCR words: " + ", ".join(sorted({t for e in ev for t in e["terms"]})),
                        region_ids=[e["region_id"] for e in ev], polygons=[e["polygon"] for e in ev],
                        excerpt=" / ".join(e["excerpt"] for e in ev[:3]), score=round(s, 4), score_kind="bm25"))
            ann = lexical.annotation_search(self.repo, pq.free_text, eligible)
            ranked["annotation"] = ann
            for aid, s in ann:
                evidence.setdefault(aid, []).append(MatchEvidence(
                    reason="USER_ANNOTATION", detail="your title/notes/tags match", score=round(s, 4),
                    score_kind="bm25"))
            channels_used += ["lexical", "annotation"]

        if (pq.free_text or similar_ref) and any(c in req.channels for c in ("ocr_semantic", "visual")):
            from services.search.vectors import semantic_channels

            sem = semantic_channels(self.repo, self.cfg, pq.free_text, eligible, req, similar_ref)
            for name, lst in sem.ranked.items():
                ranked[name] = lst
                channels_used.append(name)
            for aid, evs in sem.evidence.items():
                evidence.setdefault(aid, []).extend(evs)
            degraded += sem.degraded

        has_intent = bool(pq.free_text or pq.text_phrases or similar_ref)
        if has_intent:
            fused, ranks, scores = self._fuse(ranked)
        else:
            # Filter-only browse: newest first, still with filter evidence.
            order = self.repo.query(
                f"SELECT id FROM assets WHERE id IN ({','.join('?' * len(eligible))}) ORDER BY created_at DESC, id",
                tuple(eligible)) if eligible else []
            fused = [(r["id"], 0.0) for r in order]
            ranks, scores = {}, {}

        for aid, evs in filter_ev.items():
            if aid in eligible:
                evidence.setdefault(aid, []).extend(evs)

        revs = {}
        if fused:
            ids = [a for a, _ in fused]
            for r in self.repo.query(
                    f"SELECT id, metadata_revision FROM assets WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)):
                revs[r["id"]] = r["metadata_revision"]
        hits = [SearchHit(asset_id=aid, metadata_revision=revs.get(aid, 0), score=round(s, 6),
                          channel_ranks=ranks.get(aid, {}), channel_scores=scores.get(aid, {}),
                          reasons=evidence.get(aid, []))
                for aid, s in fused if aid in revs]
        if req.collapse_duplicates:
            hits = _collapse_duplicates(self.repo, hits)
        total = len(hits)
        hits = hits[req.offset:req.offset + req.limit]
        resp = SearchResponse(query=pq, hits=hits, total_candidates=total, channels_used=channels_used,
                              degraded=degraded, index_revision=self.index_revision(),
                              elapsed_ms=round((time.perf_counter() - t0) * 1000, 2))
        self._cache[key] = resp.model_copy(deep=True)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return resp

    def find_similar(self, asset_id: str, crop: tuple[float, float, float, float] | None = None,
                     query: str = "", limit: int = 40) -> SearchResponse:
        return self.search(SearchRequest(query=query, library_id=self.cfg.library_id, limit=limit,
                                         similar_to=asset_id, crop=crop, channels=["visual"]))

    # ------------------------------------------------------------------
    def _fuse(self, ranked: dict[str, list[tuple[str, float]]]):
        fused: dict[str, float] = {}
        ranks: dict[str, dict[str, int]] = {}
        scores: dict[str, dict[str, float]] = {}
        for ch, lst in ranked.items():
            w = self.weights.get(ch, 1.0)
            for i, (aid, s) in enumerate(lst):
                rank = i + 1
                fused[aid] = fused.get(aid, 0.0) + w / (self.rrf_k + rank)
                ranks.setdefault(aid, {})[ch] = rank
                scores.setdefault(aid, {})[ch] = round(float(s), 6)
        order = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
        return order, ranks, scores

    def _eligible(self, pq: ParsedQuery, library_id: str) -> tuple[set[str], dict[str, list[MatchEvidence]]]:
        status_filters = [f.value for f in pq.filters if f.key == "status"]
        sql = "SELECT id FROM assets WHERE library_id=? AND deleted_at IS NULL"
        params: list = [library_id]
        if not status_filters:
            sql += " AND metadata_revision > 0"
        for f in pq.filters:
            if f.key == "format":
                mime = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(f.value)
                if mime is None:
                    raise SearchError("format: must be jpeg, png or webp")
                sql += " AND mime=?"
                params.append(mime)
            elif f.key in {"after", "before"}:
                ts = datetime.combine(date.fromisoformat(f.value), datetime.min.time()).timestamp()
                sql += " AND created_at >= ?" if f.key == "after" else " AND created_at < ?"
                params.append(ts)
        ids = {r["id"] for r in self.repo.query(sql, tuple(params))}
        evidence: dict[str, list[MatchEvidence]] = {}
        for f in pq.filters:
            if f.key in {"format", "after", "before"}:
                continue
            matched, ev = self._apply_filter(f, ids)
            ids &= matched
            for aid, e in ev.items():
                evidence.setdefault(aid, []).extend(e)
        return ids, evidence

    def _apply_filter(self, f: Filter, ids: set[str]) -> tuple[set[str], dict[str, list[MatchEvidence]]]:
        ev: dict[str, list[MatchEvidence]] = {}
        if f.key == "status":
            allowed = {"complete", "partial", "error", "pending"}
            if f.value not in allowed:
                raise SearchError(f"status: must be one of {sorted(allowed)}")
            out = set()
            for aid in ids:
                st = asset_status(self.repo, aid)
                if st == f.value:
                    out.add(aid)
            return out, ev
        if f.key == "tag":
            rows = self.repo.query(
                "SELECT a.asset_id FROM user_annotations a, json_each(a.tags) t WHERE lower(t.value)=lower(?)",
                (f.value,))
            out = {r["asset_id"] for r in rows} & ids
            for aid in out:
                ev[aid] = [MatchEvidence(reason="USER_ANNOTATION", detail=f"tagged '{f.value}' by you")]
            return out, ev
        if f.key == "object":
            label = resolve_object_label(self.cfg, f.value)
            if label is None:
                sup = ", ".join(sorted(object_labels(self.cfg))[:12])
                raise SearchError(
                    f"object:{f.value} is not in the detector's supported vocabulary (COCO labels such as {sup}, ...). "
                    f"Search '{f.value}' as free text for an approximate visual match instead.")
            thr = catalog()["object_threshold"]
            rows = self.repo.query("SELECT asset_id, obs_id, score, box FROM object_observations WHERE label=? AND score>=?"
                                   " ORDER BY score DESC", (label, thr))
            out = set()
            for r in rows:
                if r["asset_id"] in ids:
                    out.add(r["asset_id"])
                    ev.setdefault(r["asset_id"], []).append(MatchEvidence(
                        reason="OBJECT_DETECTION", detail=f"detected {label}", box=tuple(json.loads(r["box"])),
                        score=round(r["score"], 4), score_kind="raw_detector"))
            return out, ev
        if f.key == "collection":
            from services.organize.overrides import collection_members_for_filter

            out = collection_members_for_filter(self.repo, f.value) & ids
            for aid in out:
                ev[aid] = [MatchEvidence(reason="COLLECTION", detail=f"member of collection {f.value}")]
            return out, ev
        # Decision-backed filters.
        qid, value = FILTER_QUESTION(f.key, f.value)
        thr = catalog()["filter_threshold"]
        out = set()
        rows = self.repo.query("SELECT asset_id, dtype, value, p_value, probs, status FROM decisions WHERE question_id=?",
                               (qid,))
        machine = {r["asset_id"]: r for r in rows}
        overrides = {r["asset_id"]: r["value"] for r in self.repo.query(
            "SELECT asset_id, value FROM metadata_overrides WHERE question_id=?", (qid,))}
        reason = {"source": "SOURCE_CONTEXT", "scene": "SCENE_DECISION"}.get(f.key, "CONTEXT_DECISION")
        for aid in ids:
            if aid in overrides:
                ok = overrides[aid] == value
                if ok:
                    out.add(aid)
                    ev[aid] = [MatchEvidence(reason=reason, detail=f"{qid} = {value} (your correction)",
                                             score_kind="user_override")]
                continue
            r = machine.get(aid)
            if r is None or r["status"] != "complete":
                continue
            if r["dtype"] == "noul":
                p = float(r["p_value"])
                if value == "yes" and p >= thr:
                    out.add(aid)
                    ev[aid] = [MatchEvidence(reason=reason, detail=f"{qid}: P(yes)={p:.2f} (uncalibrated)",
                                             score=round(p, 4), score_kind="zero_shot_softmax_uncalibrated")]
            elif r["value"] == value:
                p = float(r["p_value"])
                out.add(aid)
                ev[aid] = [MatchEvidence(reason=reason, detail=f"{qid} = {value}, P={p:.2f} (uncalibrated)",
                                         score=round(p, 4), score_kind="zero_shot_softmax_uncalibrated")]
        return out, ev


def asset_status(repo: Repository, asset_id: str) -> str:
    """complete | partial | error | pending — from the newest job + active metadata."""
    a = repo.query_one("SELECT metadata_revision FROM assets WHERE id=?", (asset_id,))
    job = repo.query_one("SELECT status FROM jobs WHERE asset_id=? ORDER BY created_at DESC LIMIT 1", (asset_id,))
    if job and job["status"] in {"queued", "running"}:
        return "pending"
    if a is None or a["metadata_revision"] == 0:
        return "error" if job and job["status"] == "error" else "pending"
    if job and job["status"] == "error":
        return "error"
    m = repo.query_one("SELECT m.payload FROM metadata_revisions m JOIN assets a ON a.id=m.asset_id AND"
                       " a.metadata_revision=m.revision WHERE a.id=?", (asset_id,))
    return "partial" if m and json.loads(m["payload"]).get("partial") else "complete"


def _collapse_duplicates(repo: Repository, hits: list[SearchHit]) -> list[SearchHit]:
    rows = repo.query(
        "SELECT m.collection_id, m.asset_id FROM memberships m JOIN collections c ON c.id=m.collection_id"
        " WHERE c.ctype='duplicate' AND c.retired_at IS NULL AND m.state!='excluded'")
    if not rows:
        return hits
    group_of: dict[str, str] = {}
    for r in rows:
        group_of[r["asset_id"]] = r["collection_id"]
    out: list[SearchHit] = []
    leader: dict[str, SearchHit] = {}
    for h in hits:
        g = group_of.get(h.asset_id)
        if g is None:
            out.append(h)
        elif g not in leader:
            leader[g] = h
            out.append(h)
        else:
            leader[g].duplicate_count += 1
            leader[g].duplicate_ids.append(h.asset_id)
    return out
