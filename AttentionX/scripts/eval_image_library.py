#!/usr/bin/env python3
"""Evaluate the image library against the labeled dev/test set.

  python scripts/eval_image_library.py --fit-calibration   # fit head calibration on DEV only
  python scripts/eval_image_library.py --tune              # threshold sweeps on DEV only
  python scripts/eval_image_library.py                     # full report (TEST split), writes reports/

Relevance judgments are derived from generator labels (see make_eval_set.py);
there is no second human rater. Everything reported here is measured on
this synthetic-rendered + real-photo set, never on the requested consented
500-image pilot (NOT AVAILABLE).
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.analyze.ocr import normalize_for_search  # noqa: E402
from services.library.config import config_from_env  # noqa: E402
from services.library.registry import Library  # noqa: E402
from services.search.lexical import find_occurrences  # noqa: E402

FAMILY_CONCEPT = {  # which generator families express each OCR-meaning concept
    "skew": {"skew", "art0", "deck0"},
    "llm_eval": {"llm_eval"},
    "k8s": {"k8s", "art1", "deck3"},
    "testing": {"testing"},
    "course": {"course", "deck4", "letter2"},
    "career": {"career"},
    "hiring_fe": {"hiring_fe"},
}


# ---------------------------------------------------------------------------
def load(lib_root: Path, eval_set: Path):
    labels = [json.loads(l) for l in (eval_set / "labels.jsonl").read_text().splitlines() if l.strip()]
    mapping = json.loads((lib_root / "eval_mapping.json").read_text())
    by_asset: dict[str, dict] = {}
    conflicts = 0
    for r in labels:
        aid = mapping[r["id"]]
        if aid in by_asset:
            if by_asset[aid]["split"] != r["split"]:
                conflicts += 1
            continue
        by_asset[aid] = r
    return labels, by_asset, conflicts


def split_ids(by_asset, split):
    return {a for a, r in by_asset.items() if split is None or r["split"] == split}


def ndcg_at(ranked: list[str], rel: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, a in enumerate(ranked[:k]) if a in rel)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(rel))))
    return dcg / idcg if idcg else float("nan")


def recall_at(ranked: list[str], rel: set[str], k: int = 10) -> float:
    """Capped recall: |top-k ∩ rel| / min(|rel|, k) (so large relevant sets are not capped at k/|rel|)."""
    return len(set(ranked[:k]) & rel) / min(len(rel), k) if rel else float("nan")


def mean(xs):
    xs = [x for x in xs if x == x]
    return round(statistics.fmean(xs), 4) if xs else None


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_text(lib, aid):
    m = lib.asset_detail(aid)["metadata"]
    if not m or not m.get("ocr"):
        return None, m
    regs = sorted(m["ocr"]["regions"], key=lambda r: r["reading_order"])
    return " ".join(r["raw_text"] for r in regs), m


def eval_ocr(lib, by_asset, split):
    from rapidfuzz.distance import Levenshtein

    rows = []
    for aid, r in by_asset.items():
        if split and r["split"] != split:
            continue
        gt = r.get("gt_text")
        if not gt or not gt.strip():
            continue
        txt, meta = ocr_text(lib, aid)
        if txt is None:
            continue
        g = " ".join(gt.split())
        o = " ".join(txt.split())
        cer = Levenshtein.distance(o, g) / max(1, len(g))
        g_ns, o_ns = re.sub(r"\s+", "", g), re.sub(r"\s+", "", o)
        cer_nospace = Levenshtein.distance(o_ns, g_ns) / max(1, len(g_ns))
        gw = Counter(w.lower() for w in re.findall(r"\w+", g))
        ow = Counter(w.lower() for w in re.findall(r"\w+", o))
        word_recall = sum(min(c, ow[w]) for w, c in gw.items()) / max(1, sum(gw.values()))
        tags = []
        n = r.get("notes", "")
        if "dark" in n:
            tags.append("dark")
        if "mobile" in n:
            tags.append("mobile")
        if r["category"].endswith("variant"):
            tags.append("reencoded_variant")
        if r["category"] == "linkedin_tall_feed":
            tags.append("tall")
        if r["category"] == "scanned_document":
            tags.append("scanned")
        rows.append({"asset": aid, "category": r["category"], "tags": tags, "cer": cer, "cer_nospace": cer_nospace,
                     "word_recall": word_recall, "complete": meta["ocr"]["complete"],
                     "tiles": len(meta["ocr"]["tiles"])})
    out = {"n": len(rows)}
    clean = [x for x in rows if x["category"] in {"linkedin_post", "code", "article", "chat", "app_settings", "slide"}
             and not x["tags"]]
    out["clean"] = {"n": len(clean), "cer_mean": mean([x["cer"] for x in clean]),
                    "cer_median": round(statistics.median([x["cer"] for x in clean]), 4) if clean else None,
                    "cer_nospace_mean": mean([x["cer_nospace"] for x in clean]),
                    "word_recall_mean": mean([x["word_recall"] for x in clean])}
    by_cat = defaultdict(list)
    for x in rows:
        by_cat[x["category"]].append(x)
        for t in x["tags"]:
            by_cat["tag:" + t].append(x)
    out["by_group"] = {k: {"n": len(v), "cer_mean": mean([x["cer"] for x in v]),
                           "cer_nospace_mean": mean([x["cer_nospace"] for x in v]),
                           "word_recall_mean": mean([x["word_recall"] for x in v]),
                           "tiles_max": max(x["tiles"] for x in v)} for k, v in sorted(by_cat.items())}
    return out


def eval_literal(lib, by_asset, split, n_queries=60, seed=7):
    rnd = random.Random(seed)
    gts = {a: normalize_for_search(" ".join(r["gt_text"].split())) for a, r in by_asset.items()
           if r.get("gt_text") and r["gt_text"].strip()}
    candidates = [a for a in gts if split is None or by_asset[a]["split"] == split]
    queries = []
    tries = 0
    while len(queries) < n_queries and tries < 5000:
        tries += 1
        a = rnd.choice(candidates)
        words = [w for w in gts[a].split() if re.fullmatch(r"[a-z][a-z'-]{3,}", w)]
        if len(words) < 3:
            continue
        i = rnd.randrange(0, len(words) - 1)
        k = rnd.choice([1, 2, 3])
        phrase = " ".join(words[i:i + k])
        if phrase not in gts[a] or phrase in {q["phrase"] for q in queries}:
            continue
        rel = {b for b, t in gts.items() if find_occurrences(t, phrase)}
        if len(rel) > 25:  # too generic ("comment", "reactions"): not a discriminating literal query
            continue
        queries.append({"phrase": phrase, "rel": rel})
    rec, ocr_miss, index_miss, merge_miss, spaceless_hits = [], 0, 0, 0, 0
    for q in queries:
        resp = lib.search(f'text:"{q["phrase"]}"', limit=50, collapse_duplicates=False)
        ranked = [h.asset_id for h in resp.hits]
        rec.append(recall_at(ranked, q["rel"]))
        spaceless_hits += sum(1 for h in resp.hits for e in h.reasons if e.score_kind == "literal_match_ignoring_spaces")
        for b in q["rel"] - set(ranked):
            t, _ = ocr_text(lib, b)
            flat = normalize_for_search(t or "")
            if find_occurrences(flat, q["phrase"]) or (" " in q["phrase"] and
                                                       q["phrase"].replace(" ", "") in flat.replace(" ", "")):
                index_miss += 1       # the search should have found it
            elif q["phrase"] in flat or q["phrase"].replace(" ", "") in flat.replace(" ", ""):
                merge_miss += 1       # present only glued to neighbouring OCR text (no word boundary)
            else:
                ocr_miss += 1         # OCR did not produce the text
    return {"queries": len(queries), "recall_at_10": mean(rec), "missed_relevant_ocr_miss": ocr_miss,
            "missed_relevant_ocr_word_merge": merge_miss,
            "missed_relevant_index_miss": index_miss, "results_via_spaceless_fallback": spaceless_hits,
            "examples": [q["phrase"] for q in queries[:12]]}


# ---------------------------------------------------------------------------
# Judged queries
# ---------------------------------------------------------------------------

def judged_queries(by_asset, eligible):
    def where(pred):
        return {a for a, r in by_asset.items() if a in eligible and pred(r)}

    def fam(concept):
        fams = FAMILY_CONCEPT[concept]
        return where(lambda r: (r.get("family") in fams))

    def sp(s):
        return where(lambda r: r.get("narrow_group") == f"flower:{s}")

    Q = []
    for q, s in [("daisy flowers", "daisy"), ("a white daisy with a yellow center", "daisy"),
                 ("dandelions", "dandelion"), ("a dandelion seed head", "dandelion"), ("red roses", "roses"),
                 ("a bouquet of roses", "roses"), ("sunflowers", "sunflowers"), ("a field of sunflowers", "sunflowers"),
                 ("tulips", "tulips"), ("colorful tulips in a garden", "tulips")]:
        Q.append(("visual", q, sp(s)))
    Q += [("visual", "a cat", where(lambda r: "cat" in r["objects"])),
          ("visual", "a cup of coffee", where(lambda r: "cup" in r["objects"])),
          ("visual", "an astronaut", where(lambda r: r["notes"] == "astronaut")),
          ("visual", "a rocket launch", where(lambda r: r["notes"] == "rocket"))]
    Q += [("ocr_meaning", "posts discussing train-serving skew", fam("skew")),
          ("ocr_meaning", "features differ between training and production", fam("skew")),
          ("ocr_meaning", "how to evaluate large language models", fam("llm_eval")),
          ("ocr_meaning", "catching hallucinations before a release", fam("llm_eval")),
          ("ocr_meaning", "kubernetes deployment problems", fam("k8s")),
          ("ocr_meaning", "health checks restarting containers", fam("k8s")),
          ("ocr_meaning", "dealing with flaky tests in continuous integration", fam("testing")),
          ("ocr_meaning", "online courses and studying", fam("course")),
          ("ocr_meaning", "celebrating a promotion or a new job", fam("career")),
          ("ocr_meaning", "frontend developer job openings", fam("hiring_fe"))]
    Q += [("source_context", "source:linkedin", where(lambda r: r["source_app"] == "linkedin")),
          ("source_context", "capture:screenshot",
           where(lambda r: r["capture_type"] == "screenshot" and not r["capture_ambiguous"])),
          ("source_context", "capture:photo", where(lambda r: r["capture_type"] == "photo" and not r["capture_ambiguous"])),
          ("source_context", "context:source_code", where(lambda r: r["context"].get("source_code"))),
          ("source_context", "context:conversation", where(lambda r: r["context"].get("conversation"))),
          ("source_context", "context:presentation_slide", where(lambda r: r["context"].get("presentation_slide"))),
          ("source_context", "context:film_tv_frame", where(lambda r: r["context"].get("film_tv_frame"))),
          ("source_context", "context:article", where(lambda r: r["context"].get("article"))),
          ("source_context", "collection:linkedin_screenshots", where(lambda r: r["source_app"] == "linkedin")),
          ("source_context", "collection:movie_tv_frames", where(lambda r: r["context"].get("film_tv_frame")))]
    Q += [("combined", 'source:linkedin text:"hiring"',
           where(lambda r: r["source_app"] == "linkedin" and "hiring" in normalize_for_search(r["gt_text"] or ""))),
          ("combined", "LinkedIn ML jobs mentioning Python",
           where(lambda r: r["source_app"] == "linkedin" and "hiring" in r["topics"] and "ai_ml" in r["topics"]
                 and "python" in (r["gt_text"] or "").lower())),
          ("combined", "LinkedIn posts about machine learning jobs",
           where(lambda r: r["source_app"] == "linkedin" and "hiring" in r["topics"] and "ai_ml" in r["topics"])),
          ("combined", "source:linkedin kubernetes", where(lambda r: r["source_app"] == "linkedin" and r["family"] == "k8s")),
          ("combined", "python training loop code", where(lambda r: r.get("family") == "code:python_train")),
          ("combined", "chat about a failed deploy", where(lambda r: r.get("family") == "chat1")),
          ("combined", 'context:source_code text:"select"', where(lambda r: r.get("family") == "code:sql_report")),
          ("combined", "job posts for frontend engineers", where(lambda r: r.get("family") == "hiring_fe")),
          ("combined", "slides about kubernetes", where(lambda r: r.get("family") == "deck3"))]
    Q += [("visual", "a field of yellow flowers", sp("sunflowers") | sp("dandelion")),
          ("ocr_meaning", "benchmarks and golden sets for model quality", fam("llm_eval"))]
    return Q


def reference_queries(by_asset, eligible, split, seed=11):
    rnd = random.Random(seed)
    Q = []
    for s in ["daisy", "dandelion", "roses", "sunflowers", "tulips"]:
        refs = sorted(a for a, r in by_asset.items() if a in eligible and r["narrow_group"] == f"flower:{s}"
                      and r["category"] == "photo_flower" and (split is None or r["split"] == split))
        for ref in rnd.sample(refs, min(2, len(refs))):
            rel = {a for a, r in by_asset.items() if a in eligible and r["narrow_group"] == f"flower:{s}"} - {ref}
            Q.append(("reference", ref, None, rel))
        if refs:
            ref = refs[-1]
            rel = {a for a, r in by_asset.items() if a in eligible and r["narrow_group"] == f"flower:{s}"}
            Q.append(("crop", ref, (0.2, 0.2, 0.8, 0.8), rel))
    films = sorted({r["narrow_group"] for a, r in by_asset.items() if r["category"] == "film_frame_synthetic"})
    for g in films[:2]:
        ref = sorted(a for a, r in by_asset.items() if r["narrow_group"] == g and a in eligible)[0]
        Q.append(("reference", ref, None, {a for a, r in by_asset.items() if r["narrow_group"] == g} - {ref}))
    return Q


NO_RELEVANT = ['text:"quantum banana xylophone"', "a snowy mountain with skiers", "a bowl of ramen noodles",
               'text:"zzqx"', "a red sports car on a race track"]


def run_queries(lib, Q, refQ, channels=None, restrict: set[str] | None = None):
    """``restrict``: judge only these assets (results outside are dropped), used for dev-only tuning."""
    fams = defaultdict(lambda: {"ndcg": [], "recall": [], "p10": [], "n": 0})
    lat = []
    per_query = []
    for fam, q, rel in Q:
        if not rel:
            continue
        t = time.perf_counter()
        resp = lib.search(q, limit=200 if restrict else 50, collapse_duplicates=False, channels=channels)
        lat.append((time.perf_counter() - t) * 1000)
        ranked = [h.asset_id for h in resp.hits if restrict is None or h.asset_id in restrict]
        if restrict is not None:
            rel = rel & restrict
            if not rel:
                continue
        f = fams[fam]
        f["ndcg"].append(ndcg_at(ranked, rel))
        f["recall"].append(recall_at(ranked, rel))
        f["p10"].append(len(set(ranked[:10]) & rel) / 10)
        f["n"] += 1
        per_query.append({"family": fam, "query": q, "relevant": len(rel), "returned": len(ranked),
                          "ndcg10": round(ndcg_at(ranked, rel), 4), "recall10": round(recall_at(ranked, rel), 4)})
    if channels is None or "visual" in channels:
        for fam, ref, crop, rel in refQ:
            resp = lib.find_similar(ref, crop=crop, limit=50)
            ranked = [h.asset_id for h in resp.hits]
            f = fams[fam]
            f["ndcg"].append(ndcg_at(ranked, rel))
            f["recall"].append(recall_at(ranked, rel))
            f["p10"].append(len(set(ranked[:10]) & rel) / 10)
            f["n"] += 1
            per_query.append({"family": fam, "query": f"similar:{ref}" + (f" crop={crop}" if crop else ""),
                              "relevant": len(rel), "returned": len(ranked),
                              "ndcg10": round(ndcg_at(ranked, rel), 4), "recall10": round(recall_at(ranked, rel), 4)})
    summary = {k: {"queries": v["n"], "ndcg_at_10": mean(v["ndcg"]), "recall_at_10": mean(v["recall"]),
                   "p_at_10": mean(v["p10"])} for k, v in sorted(fams.items())}
    return summary, per_query, lat


# ---------------------------------------------------------------------------
# Heads, collections, duplicates, groups
# ---------------------------------------------------------------------------

HEAD_LABEL = {
    "context.film_tv_frame": lambda r: r["context"].get("film_tv_frame"),
    "context.presentation_slide": lambda r: r["context"].get("presentation_slide"),
    "context.source_code": lambda r: r["context"].get("source_code"),
    "context.job_posting": lambda r: r["context"].get("job_posting"),
    "context.article": lambda r: r["context"].get("article"),
    "context.conversation": lambda r: r["context"].get("conversation"),
    "topic.hiring": lambda r: "hiring" in r["topics"],
    "topic.ai_ml": lambda r: "ai_ml" in r["topics"],
    "topic.software_development": lambda r: "software_development" in r["topics"],
    "topic.education": lambda r: "education" in r["topics"],
    "topic.entertainment": lambda r: "entertainment" in r["topics"],
}
SCENES = ["scene.beach", "scene.city_street", "scene.forest", "scene.mountain", "scene.office", "scene.kitchen",
          "scene.classroom", "scene.stadium"]


def decisions_of(lib, aid):
    rows = lib.repo.query("SELECT question_id, dtype, value, p_value, probs, status FROM decisions WHERE asset_id=?",
                          (aid,))
    return {r["question_id"]: dict(r) for r in rows}


def ece(probs, labels, bins=10):
    probs, labels = np.asarray(probs), np.asarray(labels, dtype=float)
    e = 0.0
    for b in range(bins):
        m = (probs >= b / bins) & (probs < (b + 1) / bins if b < bins - 1 else probs <= 1)
        if m.any():
            e += m.mean() * abs(probs[m].mean() - labels[m].mean())
    return float(e)


def reliability(probs, labels, bins=5):
    probs, labels = np.asarray(probs), np.asarray(labels, dtype=float)
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        m = (probs >= lo) & ((probs < hi) if b < bins - 1 else (probs <= hi))
        if m.any():
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_p": round(float(probs[m].mean()), 3),
                        "frac_pos": round(float(labels[m].mean()), 3)})
    return out


def eval_heads(lib, by_asset, split):
    out = {}
    ids = [a for a, r in by_asset.items() if split is None or r["split"] == split]
    dec = {a: decisions_of(lib, a) for a in ids}
    for qid, lab in HEAD_LABEL.items():
        ps, ys = [], []
        for a in ids:
            d = dec[a].get(qid)
            if d is None or d["status"] != "complete":
                continue
            ps.append(float(d["p_value"]))
            ys.append(bool(lab(by_asset[a])))
        if not ps:
            continue
        res = {"n": len(ps), "positives": int(sum(ys)), "brier": round(float(np.mean((np.array(ps) - np.array(ys)) ** 2)), 4),
               "ece": round(ece(ps, ys), 4), "reliability": reliability(ps, ys)}
        for thr in (0.5, 0.8):
            pred = [p >= thr for p in ps]
            tp = sum(1 for p, y in zip(pred, ys) if p and y)
            fp = sum(1 for p, y in zip(pred, ys) if p and not y)
            fn = sum(1 for p, y in zip(pred, ys) if not p and y)
            res[f"precision@{thr}"] = round(tp / (tp + fp), 4) if tp + fp else None
            res[f"recall@{thr}"] = round(tp / (tp + fn), 4) if tp + fn else None
        out[qid] = res
    # capture_type accuracy (non-ambiguous)
    conf = Counter()
    n = correct = abst = 0
    for a in ids:
        r = by_asset[a]
        if r["capture_ambiguous"] or not r["capture_type"]:
            continue
        d = dec[a].get("capture_type")
        if d is None:
            continue
        n += 1
        if d["status"] != "complete":
            abst += 1
            conf[(r["capture_type"], "abstained")] += 1
            continue
        conf[(r["capture_type"], d["value"])] += 1
        correct += d["value"] == r["capture_type"]
    out["capture_type"] = {"n": n, "accuracy_decided": round(correct / max(1, n - abst), 4), "abstained": abst,
                           "confusion": {f"{k[0]}->{k[1]}": v for k, v in sorted(conf.items())}}
    # source_app = linkedin as binary on labeled screenshots
    tp = fp = fn = tn = abst = 0
    for a in ids:
        r = by_asset[a]
        d = dec[a].get("source_app")
        is_li = r["source_app"] == "linkedin"
        pred = d is not None and d["status"] == "complete" and d["value"] == "linkedin"
        if d is not None and d["status"] == "abstained":
            abst += 1
        tp += pred and is_li
        fp += pred and not is_li
        fn += (not pred) and is_li
        tn += (not pred) and not is_li
    out["source_app.linkedin"] = {"precision": round(tp / (tp + fp), 4) if tp + fp else None,
                                  "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                                  "tp": tp, "fp": fp, "fn": fn, "abstained": abst}
    # Scenes: no positives exist in this set -> only false-positive rate measurable.
    fpr = {}
    for s in SCENES:
        ps = [float(dec[a][s]["p_value"]) for a in ids if s in dec[a] and dec[a][s]["status"] == "complete"]
        fpr[s] = {"n": len(ps), "fp@0.5": sum(p >= 0.5 for p in ps), "fp@0.8": sum(p >= 0.8 for p in ps)}
    out["scenes_no_positive_labels"] = fpr
    return out


def fit_calibration(lib, by_asset, out_path: Path):
    from sklearn.linear_model import LogisticRegression

    from services.analyze.context import HEAD_FEATURES

    ids = [a for a, r in by_asset.items() if r["split"] == "dev"]
    heads = {}
    for qid, lab in HEAD_LABEL.items():
        FEATURES = HEAD_FEATURES.get(qid, ())
        if not FEATURES:
            continue
        X, y = [], []
        for a in ids:
            m = lib.asset_detail(a)["metadata"]
            d = (m or {}).get("decisions", {}).get(qid)
            if not d or d["status"] != "complete" or "features" not in d["gates"]:
                continue
            X.append([d["gates"]["features"][k] for k in FEATURES])
            y.append(int(bool(lab(by_asset[a]))))
        if sum(y) < 5 or len(y) - sum(y) < 5:
            continue
        clf = LogisticRegression(C=1.0, max_iter=1000).fit(np.array(X), np.array(y))
        heads[qid] = {"bias": float(clf.intercept_[0]),
                      "weights": {k: float(w) for k, w in zip(FEATURES, clf.coef_[0])},
                      "n": len(y), "positives": int(sum(y))}
    # Content-derived version: new weights => new version => context cache key changes.
    import hashlib

    digest = hashlib.sha256(json.dumps(heads, sort_keys=True).encode()).hexdigest()[:10]
    version = f"platt-synthetic-dev-{time.strftime('%Y%m%d')}-{digest}"
    doc = {"version": version, "fitted_on": "dev split of data/eval_set (synthetic-rendered screenshots + CC-BY photos)",
           "method": "per-head logistic regression over HEAD_FEATURES (services/analyze/context.py)",
           "warning": "Fitted on synthetic data; re-fit on the consented pilot before trusting absolute values.",
           "heads": heads}
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True))
    return doc


def eval_collections(lib, by_asset, split):
    ids = split_ids(by_asset, split)
    spec = {
        "linkedin_screenshots": lambda r: r["source_app"] == "linkedin",
        "movie_tv_frames": lambda r: r["context"].get("film_tv_frame"),
        "source_code": lambda r: r["context"].get("source_code"),
        "conversations": lambda r: r["context"].get("conversation"),
        "presentation_slides": lambda r: r["context"].get("presentation_slide"),
        "documents": lambda r: r["context"].get("article") or r["capture_type"] == "scanned_document",
        "photos": lambda r: r["capture_type"] == "photo" and not r["capture_ambiguous"],
    }
    out = {}
    for key, lab in spec.items():
        c = lib.collection(key)
        members = {m.asset_id for m in c.members if m.state != "excluded"} if c else set()
        members &= ids
        rel = {a for a in ids if lab(by_asset[a])}
        tp = len(members & rel)
        fps = sorted(members - rel)
        out[key] = {"precision": round(tp / len(members), 4) if members else None,
                    "recall": round(tp / len(rel), 4) if rel else None, "members": len(members), "relevant": len(rel),
                    "false_positive_categories": dict(Counter(by_asset[a]["category"] for a in fps))}
    nr = lib.collection("needs_review")
    out["needs_review"] = {"members": len({m.asset_id for m in nr.members} & ids) if nr else 0}
    return out


def eval_duplicates(lib, by_asset, split):
    ids = split_ids(by_asset, split)
    groups = defaultdict(set)
    for a in ids:
        g = by_asset[a].get("near_dup_group")
        if g:
            groups[g].add(a)
    pos = {tuple(sorted((a, b))) for g in groups.values() for a in g for b in g if a < b}
    pred = set()
    for c in lib.collections(ctype="duplicate", with_members=True):
        mem = sorted({m.asset_id for m in c.members if m.state != "excluded"} & ids)
        pred |= {(a, b) for i, a in enumerate(mem) for b in mem[i + 1:]}
    tp = len(pred & pos)
    chrome_fp = sum(1 for a, b in pred - pos if by_asset[a]["source_app"] == by_asset[b]["source_app"] == "linkedin")
    crop_fp = sum(1 for a, b in pred - pos if "crop" in (by_asset[a]["category"] + by_asset[b]["category"]))
    return {"positive_pairs": len(pos), "predicted_pairs": len(pred),
            "precision": round(tp / len(pred), 4) if pred else None,
            "recall": round(tp / len(pos), 4) if pos else None,
            "false_pairs_linkedin_chrome": chrome_fp, "false_pairs_crop": crop_fp}


def bcubed(items: list[str], gold: dict[str, str], pred: dict[str, str]):
    P, R = [], []
    for i in items:
        same_pred = [j for j in items if pred[j] == pred[i]]
        same_gold = [j for j in items if gold[j] == gold[i]]
        both = sum(1 for j in same_pred if gold[j] == gold[i])
        P.append(both / len(same_pred))
        R.append(both / len(same_gold))
    p, r = statistics.fmean(P), statistics.fmean(R)
    return p, r, 2 * p * r / (p + r) if p + r else 0.0


def eval_groups(lib, by_asset, split):
    from services.organize.clustering import SCOPES

    ids = split_ids(by_asset, split)
    out = {}
    groups = lib.collections(ctype="similarity", with_members=True)
    for scope in ("photos", "movie_tv_frames", "linkedin_screenshots"):
        sc = lib.collection(scope)
        members = sorted(({m.asset_id for m in sc.members if m.state != "excluded"} if sc else set()) & ids)
        items = [a for a in members if by_asset[a].get("narrow_group")]
        if len(items) < 2:
            out[scope] = {"items": len(items), "note": "too few labeled items"}
            continue
        pred = {}
        for g in groups:
            if g.parent_id != sc.id:
                continue
            for m in g.members:
                if m.state != "excluded" and m.asset_id in items:
                    pred.setdefault(m.asset_id, g.id)
        grouped = sum(1 for a in items if a in pred)
        for a in items:
            pred.setdefault(a, f"single:{a}")
        gold = {a: by_asset[a]["narrow_group"] for a in items}
        p, r, f = bcubed(items, gold, pred)
        out[scope] = {"channel": SCOPES[scope], "items": len(items), "bcubed_precision": round(p, 4),
                      "bcubed_recall": round(r, 4), "bcubed_f1": round(f, 4),
                      "grouped_coverage": round(grouped / len(items), 4),
                      "groups": len({pred[a] for a in items if not pred[a].startswith("single:")}),
                      "gold_groups": len(set(gold.values()))}
    return out


def latency(lib):
    rows = lib.repo.query("SELECT stage, finished_at - started_at d FROM job_stages WHERE started_at IS NOT NULL AND"
                          " finished_at IS NOT NULL AND status IN ('complete','partial','not_applicable')")
    by = defaultdict(list)
    for r in rows:
        by[r["stage"]].append(r["d"])
    pct = lambda v, q: round(float(np.percentile(v, q)), 3)
    return {s: {"n": len(v), "p50_s": pct(v, 50), "p95_s": pct(v, 95), "max_s": round(max(v), 3)} for s, v in sorted(by.items())}


def hardware():
    import os

    cpu = ""
    try:
        cpu = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception:
        pass
    mem = ""
    try:
        mem = next(l.split(":", 1)[1].strip() for l in open("/proc/meminfo") if l.startswith("MemTotal"))
    except Exception:
        pass
    import onnxruntime, sqlite3

    return {"cpu": cpu, "logical_cpus": os.cpu_count(), "mem_total": mem, "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version, "onnxruntime": onnxruntime.__version__, "gpu": "none"}


# ---------------------------------------------------------------------------

def tune(lib, by_asset):
    import services.search.vectors as V
    from services.organize import clustering as C
    from services.organize import duplicates as D

    dev = split_ids(by_asset, "dev")
    Q = [q for q in judged_queries(by_asset, dev) if q[0] in {"visual", "ocr_meaning"}]
    res = {"visual_min_cos": {}, "ocr_min_cos": {}}
    base = dict(V.CHANNEL_PARAMS["visual"])
    for mc in (0.18, 0.20, 0.22, 0.24, 0.26):
        V.CHANNEL_PARAMS["visual"] = dict(base, min_cos=mc)
        lib.search_service._cache.clear()
        s, _, _ = run_queries(lib, [q for q in Q if q[0] == "visual"], [], channels=["visual"], restrict=dev)
        fp = sum(1 for q in NO_RELEVANT if not q.startswith("text:")
                 for h in lib.search(q, limit=200, channels=["visual"]).hits if h.asset_id in dev)
        res["visual_min_cos"][mc] = {"ndcg": s["visual"]["ndcg_at_10"], "no_relevant_hits": fp}
    V.CHANNEL_PARAMS["visual"] = base
    base = dict(V.CHANNEL_PARAMS["ocr_semantic"])
    visual_q = [q for q in Q if q[0] == "visual"]
    for mc in (0.30, 0.34, 0.38, 0.42, 0.46):
        V.CHANNEL_PARAMS["ocr_semantic"] = dict(base, min_cos=mc)
        lib.search_service._cache.clear()
        s, _, _ = run_queries(lib, [q for q in Q if q[0] == "ocr_meaning"], [], channels=["ocr_semantic"],
                              restrict=dev)
        # False positives: OCR-semantic hits (dev assets) for visual-only and no-relevant queries.
        qs = [q for _, q, _ in visual_q] + [q for q in NO_RELEVANT if not q.startswith("text:")]
        fp = sum(1 for q in qs for h in lib.search(q, limit=200, channels=["ocr_semantic"]).hits if h.asset_id in dev)
        res["ocr_min_cos"][mc] = {"ndcg": s["ocr_meaning"]["ndcg_at_10"], "recall": s["ocr_meaning"]["recall_at_10"],
                                  "false_positive_hits": fp}
    V.CHANNEL_PARAMS["ocr_semantic"] = base
    lib.search_service._cache.clear()
    # Clustering (dev items only)
    res["clustering"] = {}
    for scope in ("photos", "movie_tv_frames", "linkedin_screenshots"):
        ids, X = C.scope_vectors(lib.repo, scope, lib.cfg.library_id)
        keep = [i for i, a in enumerate(ids) if a in dev and by_asset[a].get("narrow_group")]
        if len(keep) < 4:
            continue
        items = [ids[i] for i in keep]
        Xs = X[keep]
        best = []
        kind = C.SCOPES[scope]
        grid_e = (0.70, 0.75, 0.80, 0.85, 0.90) if kind == "image" else (0.5, 0.6, 0.7, 0.8)
        for te in grid_e:
            for tl in (te - 0.2, te - 0.1, te - 0.05):
                groups = C.cluster(Xs, dict(C.PARAMS[kind], tau_edge=te, tau_link=tl))
                pred = {items[i]: f"g{gi}" for gi, g in enumerate(groups) for i in g}
                for a in items:
                    pred.setdefault(a, "s:" + a)
                p, r, f = bcubed(items, {a: by_asset[a]["narrow_group"] for a in items}, pred)
                cov = sum(1 for a in items if not pred[a].startswith("s:")) / len(items)
                best.append((round(f, 4), te, round(tl, 2), round(p, 4), round(r, 4), round(cov, 4)))
        best.sort(reverse=True)
        res["clustering"][scope] = best[:5]
    # Duplicates (dev)
    res["duplicates"] = {}
    orig = (D.SSIM_MIN, D.TEXT_MIN)
    for cm in (0.6, 0.7, 0.8, 0.9):
        for tm in (0.75, 0.85, 0.9):
            D.SSIM_MIN, D.TEXT_MIN = cm, tm
            groups = D.find_duplicate_groups(lib.repo, lib.cfg.library_id, library_root=lib.cfg.library_root)
            pred = set()
            for g in groups:
                mem = sorted(({g["representative"], *g["members"]}) & dev)
                pred |= {(a, b) for i, a in enumerate(mem) for b in mem[i + 1:]}
            gg = defaultdict(set)
            for a in dev:
                if by_asset[a].get("near_dup_group"):
                    gg[by_asset[a]["near_dup_group"]].add(a)
            pos = {tuple(sorted((a, b))) for g in gg.values() for a in g for b in g if a < b}
            tp = len(pred & pos)
            res["duplicates"][f"ssim{cm}_text{tm}"] = {"precision": round(tp / len(pred), 4) if pred else None,
                                                     "recall": round(tp / len(pos), 4) if pos else None}
    D.SSIM_MIN, D.TEXT_MIN = orig
    return res


THRESHOLD_TARGETS = {  # question -> (label fn, option or None, collection precision floor or None)
    "source_app": (lambda r: r["source_app"] == "linkedin", "linkedin", 0.95),
    "context.film_tv_frame": (HEAD_LABEL["context.film_tv_frame"], None, 0.90),
    **{q: (fn, None, None) for q, fn in HEAD_LABEL.items() if q != "context.film_tv_frame"},
}


def select_thresholds(lib, by_asset) -> dict:
    """Pick per-question thresholds on the DEV split only.

    collection: max recall subject to the precision floor when one is set
    (LinkedIn >= 0.95, movie/TV >= 0.90), otherwise max F1;  filter: max F1.
    """
    dev = [a for a, r in by_asset.items() if r["split"] == "dev"]
    dec = {a: decisions_of(lib, a) for a in dev}
    grid = [round(x, 2) for x in np.arange(0.05, 0.96, 0.05)]
    out, detail = {}, {}
    for qid, (lab, option, floor) in THRESHOLD_TARGETS.items():
        pts = []
        for a in dev:
            d = dec[a].get(qid)
            if d is None or d["status"] != "complete":
                p = 0.0
            elif option:
                p = json.loads(d["probs"]).get(option, 0.0)
            else:
                p = float(d["p_value"])
            pts.append((p, bool(lab(by_asset[a]))))
        if sum(y for _, y in pts) < 3:
            continue
        rows = []
        for t in grid:
            tp = sum(1 for p, y in pts if p >= t and y)
            fp = sum(1 for p, y in pts if p >= t and not y)
            fn = sum(1 for p, y in pts if p < t and y)
            prec = tp / (tp + fp) if tp + fp else 1.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            rows.append((t, prec, rec, f1))
        best_f1 = max(rows, key=lambda r: (r[3], r[0]))
        if floor is not None:
            ok = [r for r in rows if r[1] >= floor and r[2] > 0]
            coll = max(ok, key=lambda r: (r[2], r[0])) if ok else max(rows, key=lambda r: (r[1], r[0]))
        else:
            coll = best_f1
        suffix = f"={option}" if option else ""
        out[f"collection:{qid}{suffix}"] = coll[0]
        out[f"filter:{qid}{suffix}"] = best_f1[0]
        detail[qid] = {"collection": {"t": coll[0], "precision": round(coll[1], 3), "recall": round(coll[2], 3),
                                      "floor": floor},
                       "filter": {"t": best_f1[0], "precision": round(best_f1[1], 3), "recall": round(best_f1[2], 3)}}
    import hashlib

    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:10]
    return {"version": f"dev-thresholds-{time.strftime('%Y%m%d')}-{digest}", "selected_on": "dev split (synthetic set)",
            "thresholds": out, "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", type=Path, default=ROOT / "data" / "eval_runs" / "lib")
    ap.add_argument("--eval-set", type=Path, default=ROOT / "data" / "eval_set")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("--fit-calibration", action="store_true")
    ap.add_argument("--tune", action="store_true")
    args = ap.parse_args()

    lib = Library(config_from_env(args.lib))
    labels, by_asset, conflicts = load(args.lib, args.eval_set)
    if args.fit_calibration:
        doc = fit_calibration(lib, by_asset, ROOT / "services" / "analyze" / "context_calibration.json")
        print(json.dumps({h: {"n": v["n"], "pos": v["positives"]} for h, v in doc["heads"].items()}, indent=1))
        return 0
    if args.tune:
        th = select_thresholds(lib, by_asset)
        (ROOT / "services" / "organize" / "decision_thresholds.json").write_text(json.dumps(th, indent=2, sort_keys=True))
        res = tune(lib, by_asset)
        res["decision_thresholds"] = th["detail"]
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "tuning_dev.json").write_text(json.dumps(res, indent=2, default=str))
        print(json.dumps(res, indent=1, default=str))
        return 0

    split = None if args.split == "all" else args.split
    eligible = set(by_asset)
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "split": args.split,
              "dataset": {"labels": len(labels), "assets": len(by_asset), "split_conflicts_identical_bytes": conflicts,
                          "by_split": dict(Counter(r["split"] for r in by_asset.values())),
                          "note": "synthetic-rendered screenshots + real CC-BY photos; NOT the consented pilot"},
              "hardware": hardware()}
    report["ocr"] = eval_ocr(lib, by_asset, split)
    report["literal_search"] = eval_literal(lib, by_asset, split)
    # Queries are judged over the whole library (relevance sets span both splits).
    Q = judged_queries(by_asset, eligible)
    refQ = reference_queries(by_asset, eligible, split)
    report["retrieval"] = {}
    report["retrieval_per_query"] = {}
    lat_all = {}
    for name, ch in (("hybrid", None), ("image_only", ["visual"]), ("ocr_only", ["lexical", "ocr_semantic"])):
        lib.search_service._cache.clear()
        s, per, lat = run_queries(lib, Q, refQ if name != "ocr_only" else [], channels=ch)
        report["retrieval"][name] = s
        report["retrieval_per_query"][name] = per
        lat_all[name] = lat
    nr = {}
    for q in NO_RELEVANT:
        nr[q] = len(lib.search(q, limit=50).hits)
    report["no_relevant_queries"] = nr
    report["judged_query_count"] = sum(v["queries"] for v in report["retrieval"]["hybrid"].values())
    report["heads"] = eval_heads(lib, by_asset, split)
    report["collections"] = eval_collections(lib, by_asset, split)
    report["duplicates"] = eval_duplicates(lib, by_asset, split)
    report["groups"] = eval_groups(lib, by_asset, split)
    report["stage_latency"] = latency(lib)
    # Warm search latency (cache disabled per query so it measures real work).
    warm = defaultdict(list)
    for fam, q, rel in Q * 3:
        lib.search_service._cache.clear()
        t = time.perf_counter()
        lib.search(q, limit=40)
        warm[fam].append((time.perf_counter() - t) * 1000)
    for q in ['text:"feature store"', 'text:"kubernetes"', "tag:none", "capture:photo"] * 5:
        lib.search_service._cache.clear()
        t = time.perf_counter()
        try:
            lib.search(q, limit=40, channels=["lexical"])
        except Exception:
            pass
        warm["lexical_filter"].append((time.perf_counter() - t) * 1000)
    report["search_latency_ms"] = {k: {"n": len(v), "p50": round(float(np.percentile(v, 50)), 1),
                                       "p95": round(float(np.percentile(v, 95)), 1)} for k, v in warm.items()}
    report["calibration"] = json.loads((ROOT / "services/analyze/context_calibration.json").read_text()).get("version") \
        if (ROOT / "services/analyze/context_calibration.json").exists() else None
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evaluation.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in ("ocr", "literal_search", "retrieval", "no_relevant_queries",
                                             "collections", "duplicates", "groups")}, indent=1, default=str)[:12000])
    lib.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
