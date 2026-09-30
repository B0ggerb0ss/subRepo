"""Typed image context decisions (L3b) for the versioned image question catalog.

Backend: *local CLIP zero-shot decision backend* with explicit evidence gates.
It substitutes for the OneJev profile, which could not be provisioned (see
docs/architecture-decisions/ADR-005-context-decisions.md). Every head reuses
the one global CLIP image vector already computed by ``image_embed`` — a
single image encode serves all 23 heads of groups A and B.

Per head:
- visual vote: softmax(100 * cos(image, prompt-ensemble mean)) over options
  (or yes/no prompt sets for Noul heads);
- text vote (OCR-dependent heads): softmax(25 * cos(OCR chunk, description))
  with MiniLM over *extracted* OCR text; OCR text is data, never instructions;
- gates: capture/source pixel priors, visible-UI evidence for app sources,
  code-token evidence, prose-layout evidence.
Probabilities are ``zero_shot_softmax_uncalibrated``: rankable, thresholds
must be chosen on labeled data, and they are not correctness guarantees.
Missing evidence yields ``unavailable``/``abstained``/``not_applicable``,
never a fabricated "no".
"""
from __future__ import annotations

import re
import numpy as np

from services.analyze.catalog import catalog
from services.analyze.embeddings import CLIP_LOGIT_SCALE

CONTEXT_VERSION = "context/1.4"
PROMPTS_VERSION = "prompts/1.0"
TEXT_SCALE = 25.0
PROB_KIND = "zero_shot_softmax_uncalibrated"
MODEL_ID = "clip-zero-shot+minilm@attentionx"

VISUAL_PROMPTS: dict[str, dict[str, list[str]]] = {
    "capture_type": {
        "screenshot": ["a screenshot of a computer screen", "a screenshot of a mobile app",
                       "a screenshot of a website", "a screen capture of a user interface"],
        "photo": ["a photo taken with a camera", "a photograph of a real scene", "a snapshot of people or places"],
        "scanned_document": ["a scanned document", "a scan of a printed page", "a photocopy of a paper document"],
        "graphic": ["an illustration", "a poster design", "a meme", "a logo", "a cartoon drawing"],
    },
    "source_app": {
        "linkedin": ["a screenshot of a LinkedIn post", "a screenshot of the LinkedIn feed",
                     "a screenshot of a LinkedIn job listing"],
        "youtube": ["a screenshot of a YouTube video page"],
        "github": ["a screenshot of a GitHub repository page"],
        "whatsapp": ["a screenshot of a WhatsApp chat"],
        "instagram": ["a screenshot of an Instagram post"],
        "browser": ["a screenshot of a web page in a browser", "a screenshot of a news website"],
        "other": ["a screenshot of a desktop application", "a screenshot of a phone settings screen",
                  "a screenshot of a code editor"],
    },
}

NOUL_VISUAL: dict[str, tuple[list[str], list[str]]] = {
    "context.film_tv_frame": (["a still frame from a movie", "a scene from a TV show",
                               "a cinematic film still with subtitles"],
                              ["a casual phone photo", "a screenshot of a website", "a document", "an illustration"]),
    "context.presentation_slide": (["a presentation slide", "a powerpoint slide with a title and bullet points"],
                                   ["a photo", "a screenshot of a social media feed", "a text document page"]),
    "context.source_code": (["a screenshot of source code in a code editor", "programming code on a screen"],
                            ["a screenshot of a social media post", "a photo", "a text document"]),
    "context.job_posting": (["a screenshot of a job posting", "a hiring announcement"],
                            ["a screenshot of a social media post", "a photo", "a document"]),
    "context.article": (["a screenshot of a news article", "a long text post"],
                        ["a photo", "a chat conversation", "a presentation slide"]),
    "context.conversation": (["a screenshot of a chat conversation with message bubbles", "a text message thread"],
                             ["a screenshot of a web page", "a photo", "a document"]),
    "scene.beach": (["a photo of a beach", "a sandy beach by the sea"], ["a photo of a city", "a photo indoors", "a forest"]),
    "scene.city_street": (["a photo of a city street", "an urban street with buildings"],
                          ["a photo of nature", "a photo indoors", "a beach"]),
    "scene.forest": (["a photo of a forest", "trees in a forest"], ["a city street", "a room indoors", "a beach"]),
    "scene.mountain": (["a photo of mountains", "a mountain landscape"], ["a city street", "a room indoors", "a beach"]),
    "scene.office": (["a photo of an office interior", "desks and computers in an office"],
                     ["a photo outdoors", "a kitchen", "a living room"]),
    "scene.kitchen": (["a photo of a kitchen", "a kitchen with a stove and counters"],
                      ["a photo outdoors", "an office", "a bedroom"]),
    "scene.classroom": (["a photo of a classroom", "students in a classroom"], ["a photo outdoors", "an office", "a kitchen"]),
    "scene.stadium": (["a photo of a stadium", "a sports arena with a crowd"], ["a city street", "a room indoors", "a forest"]),
    "topic.hiring": (["a job advertisement", "a we are hiring post"], ["a vacation photo", "a meme", "a news article"]),
    "topic.ai_ml": (["an image about artificial intelligence and machine learning", "a neural network diagram"],
                    ["a vacation photo", "a food photo", "a sports photo"]),
    "topic.software_development": (["an image about software development and programming"],
                                   ["a vacation photo", "a food photo", "a sports photo"]),
    "topic.education": (["an image about education and learning", "an online course"],
                        ["a vacation photo", "a food photo", "a sports photo"]),
    "topic.entertainment": (["an image about movies, music or games", "a movie scene"],
                            ["an image about finance", "a document", "a code editor"]),
}

SCENE_HEADS = ["scene.beach", "scene.city_street", "scene.forest", "scene.mountain", "scene.office",
               "scene.kitchen", "scene.classroom", "scene.stadium"]
# "None of the catalog scenes": scenes are scored with ONE softmax over the 8
# scene prompts plus these, so a flower close-up is not forced to choose between
# "forest" and a few narrow negatives (independent binary heads did exactly that).
SCENE_OTHER_PROMPTS = [
    "a close-up photo of flowers", "a photo of a plant", "a photo of a garden", "a photo of an animal",
    "a portrait of a person", "a photo of food", "a photo of an object on a table", "a photo of the sky",
    "a photo of a park", "a photo of a lake", "outer space", "a screenshot of a computer screen",
    "a document", "an illustration", "a photo of a living room", "a photo of a car",
]

TEXT_DESCRIPTIONS: dict[str, tuple[list[str], list[str]]] = {
    "context.job_posting": (["We are hiring. Apply now for this job opening, role, position and salary.",
                             "Job description: responsibilities, requirements, experience, full-time role."],
                            ["A personal story or opinion post.", "A news article about an event.",
                             "Source code of a program.", "A casual chat between friends."]),
    "context.article": (["A long-form article with several paragraphs of prose."],
                        ["A short caption.", "Program source code.", "A list of menu items.", "A chat message."]),
    "context.conversation": (["A chat conversation: hi, how are you? see you tomorrow, thanks!"],
                             ["A formal article.", "Program source code.", "A job advertisement."]),
    "topic.hiring": (["hiring, recruiting, job openings, careers, apply for a role, looking for candidates"],
                     ["cooking recipes", "sports results", "travel and holidays", "politics news", "product review"]),
    "topic.ai_ml": (["machine learning, artificial intelligence, neural networks, LLMs, model training, data science, MLOps"],
                    ["cooking recipes", "sports results", "travel and holidays", "fashion", "real estate"]),
    "topic.software_development": (["software engineering, programming, code, APIs, debugging, deployment, developers"],
                                   ["cooking recipes", "sports results", "travel and holidays", "fashion", "gardening"]),
    "topic.education": (["education, learning, courses, students, teaching, university, tutorials"],
                        ["cooking recipes", "sports results", "fashion", "real estate", "car repair"]),
    "topic.entertainment": (["movies, TV series, music, celebrities, video games, streaming, entertainment"],
                            ["tax law", "accounting", "software configuration", "medical dosage", "plumbing"]),
}

TEXT_HEADS_REQUIRE_OCR = {"context.job_posting", "context.article", "context.conversation", "topic.hiring",
                          "topic.ai_ml", "topic.software_development", "topic.education", "topic.entertainment"}

# Visible-UI evidence for app sources: short UI labels / navigation items, not
# brand mentions in body text.
UI_RULES: dict[str, list[tuple[set[str], int]]] = {
    "linkedin": [({"like", "comment", "repost", "send"}, 3),
                 ({"home", "my network", "jobs", "messaging", "notifications"}, 3),
                 ({"easy apply", "save", "applicants", "promoted", "apply"}, 2)],
    "youtube": [({"subscribe", "share", "download", "clip", "save"}, 3)],
    "github": [({"code", "issues", "pull requests", "actions", "projects", "wiki", "security", "insights"}, 4)],
    "whatsapp": [({"online", "type a message", "last seen", "typing..."}, 2)],
    "instagram": [({"follow", "add a comment...", "view all comments", "liked by"}, 2)],
}
UI_LABEL_MAX_CHARS = 28
# Likelihood ratios applied to the visual vote (tuned on the dev split, see
# reports/evaluation.md): a supported app lacking its visible UI chrome is
# nearly ruled out; when some app's chrome *is* visible, generic
# "other"/"browser" explanations are down-weighted.
LR_REQUIRED_APP_WITHOUT_UI = 0.02
LR_GENERIC_WHEN_APP_UI_SEEN = 0.1

LEXICONS: dict[str, list[str]] = {
    "context.job_posting": ["we're hiring", "we are hiring", "hiring", "open role", "join our", "join us", "apply",
                            "easy apply", "applicants", "job", "role", "position", "candidate", "salary", "/yr",
                            "full-time", "remote", "looking for"],
    "topic.hiring": ["hiring", "recruit", "open role", "job", "candidate", "apply", "interview", "join our team",
                     "careers", "position", "referral"],
    "topic.ai_ml": ["machine learning", " ml ", "model", "llm", "neural", "training", "feature store", "pytorch",
                    "data scien", "inference", "evals", "hallucination", "embedding", "mlops", "ai "],
    "topic.software_development": ["code", "kubernetes", "deploy", "api", "tests", " ci ", "developer", "sql",
                                   "container", "react", "typescript", "frontend", "backend", "debug", "git"],
    "topic.education": ["course", "learn", "student", "teach", "university", "certification", "lecture", "workshop",
                        "study", "syllabus", "tutor"],
    "topic.entertainment": ["movie", "film", "music", "series", "game", "episode", "trailer", "concert", "actor"],
    "context.conversation": ["thanks", "see you", "sounds good", "ok", "?"],
}
TEXT_DOMINANT_WORDS = 30  # enough OCR words: text-defined heads ignore the visual vote


def lexicon_score(qid: str, text_norm: str) -> float:
    terms = LEXICONS.get(qid)
    if not terms:
        return 0.0
    padded = f" {text_norm} "
    hits = sum(1 for t in terms if t in padded)
    return min(1.0, hits / 3.0)


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return float(np.log(p / (1 - p)))


def load_calibration() -> dict:
    import json
    from pathlib import Path

    f = Path(__file__).with_name("context_calibration.json")
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


FEATURES = ("visual_logit", "text_logit", "has_text", "lexicon", "code_fraction", "prose_score", "ui_any",
            "letterbox", "subtitle")
# Per-head feature sets: only signals that plausibly *cause* the label. Generic
# features such as "some app UI is visible" or "has any text" were dropped after
# the first dev fit learned dataset shortcuts from them (reports/evaluation.md).
HEAD_FEATURES: dict[str, tuple[str, ...]] = {
    # Cinematic cues are evidence, never sufficient alone: calibrated jointly with
    # the visual vote (pillarbox photos and black bars without subtitles stay negative).
    "context.film_tv_frame": ("visual_logit", "letterbox", "subtitle"),
    "context.presentation_slide": ("visual_logit",),
    "context.source_code": ("visual_logit", "code_fraction"),
    "context.job_posting": ("visual_logit", "text_logit", "lexicon"),
    "context.article": ("visual_logit", "text_logit", "prose_score"),
    "context.conversation": ("visual_logit", "text_logit", "lexicon"),
    "topic.hiring": ("visual_logit", "text_logit", "lexicon"),
    "topic.ai_ml": ("visual_logit", "text_logit", "lexicon"),
    "topic.software_development": ("visual_logit", "text_logit", "lexicon"),
    "topic.education": ("visual_logit", "text_logit", "lexicon"),
    "topic.entertainment": ("visual_logit", "text_logit", "lexicon"),
}


_CODE_RE = re.compile(r"(\bdef\b|\bclass\b|\bimport\b|\breturn\b|\bfunction\b|\bconst\b|=>|==|!=|\{|\}|;\s*$|\(\)|"
                      r"#include|\bpublic\b|\bprivate\b|\bvar\b|\blet\b|</?\w+>)")


def _softmax(x: np.ndarray, scale: float) -> np.ndarray:
    z = scale * (x - x.max())
    e = np.exp(z)
    return e / e.sum()


class ContextDecider:
    def __init__(self, clip, minilm=None) -> None:
        self.clip = clip
        self.minilm = minilm
        self._visual = {}
        self._text = {}

    def _vis(self, prompts: list[str]) -> np.ndarray:
        key = tuple(prompts)
        if key not in self._visual:
            v = self.clip.encode_texts(prompts).mean(0)
            self._visual[key] = v / np.linalg.norm(v)
        return self._visual[key]

    def _txt(self, descs: list[str]) -> np.ndarray:
        key = tuple(descs)
        if key not in self._text:
            self._text[key] = self.minilm.encode_queries(descs)
        return self._text[key]

    # -- votes -------------------------------------------------------------
    def choice_visual(self, img: np.ndarray, qid: str) -> dict[str, float]:
        opts = VISUAL_PROMPTS[qid]
        sims = np.array([float(img @ self._vis(p)) for p in opts.values()])
        probs = _softmax(sims, CLIP_LOGIT_SCALE)
        return dict(zip(opts, probs.tolist()))

    def scene_probs(self, img: np.ndarray) -> dict[str, float]:
        sims = [float(img @ self._vis(NOUL_VISUAL[q][0])) for q in SCENE_HEADS]
        sims += [float(img @ self._vis([p])) for p in SCENE_OTHER_PROMPTS]
        probs = _softmax(np.array(sims), CLIP_LOGIT_SCALE)
        return {q: float(probs[i]) for i, q in enumerate(SCENE_HEADS)}

    def noul_visual(self, img: np.ndarray, qid: str) -> float:
        yes, no = NOUL_VISUAL[qid]
        sims = np.array([float(img @ self._vis(yes)), float(img @ self._vis(no))])
        return float(_softmax(sims, CLIP_LOGIT_SCALE)[0])

    def noul_text(self, chunk_vecs: np.ndarray, qid: str) -> float | None:
        if self.minilm is None or chunk_vecs is None or len(chunk_vecs) == 0 or qid not in TEXT_DESCRIPTIONS:
            return None
        yes, no = TEXT_DESCRIPTIONS[qid]
        y = float((chunk_vecs @ self._txt(yes).T).max())
        n = float((chunk_vecs @ self._txt(no).T).max())
        return float(_softmax(np.array([y, n]), TEXT_SCALE)[0])


def ui_evidence(regions: list[dict]) -> dict[str, dict]:
    """Which supported apps show *UI chrome* in the OCR layout (short labels)."""
    labels = {}
    for r in regions:
        t = r["norm_text"].strip(" .·•|")
        if 0 < len(t) <= UI_LABEL_MAX_CHARS:
            labels.setdefault(t, []).append(r["region_id"])
            for part in re.split(r"\s*[·•|]\s*|\s{2,}", t):
                if part and part != t:
                    labels.setdefault(part, []).append(r["region_id"])
    out = {}
    for app, rules in UI_RULES.items():
        best = None
        for tokens, need in rules:
            hit = sorted(tok for tok in tokens if tok in labels)
            if len(hit) >= need:
                refs = sorted({rid for tok in hit for rid in labels[tok]})
                cand = {"tokens": hit, "region_ids": refs, "rule_min": need}
                if best is None or len(hit) > len(best["tokens"]):
                    best = cand
        if best:
            out[app] = best
    return out


def code_fraction(regions: list[dict]) -> float:
    if not regions:
        return 0.0
    return sum(1 for r in regions if _CODE_RE.search(r["raw_text"])) / len(regions)


def subtitle_score(regions: list[dict]) -> float:
    """A short OCR line centered horizontally in the lower 35% of the frame."""
    for r in regions:
        xs = [p[0] for p in r["polygon"]]
        ys = [p[1] for p in r["polygon"]]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        if 0.4 <= cx <= 0.6 and cy >= 0.65 and 5 <= len(r["raw_text"]) <= 80 and (max(xs) - min(xs)) < 0.9:
            return 1.0
    return 0.0


def prose_score(regions: list[dict]) -> float:
    long_lines = [r for r in regions if len(r["raw_text"]) >= 40 and len(r["raw_text"].split()) >= 7]
    return min(1.0, len(long_lines) / 8.0)


def _noul(qid: str, p: float, refs: list[str], gates: dict, kind: str = PROB_KIND, missing=None) -> dict:
    p = float(min(max(p, 0.0), 1.0))
    return {"question_id": qid, "dtype": "noul", "value": p, "probs": {"yes": p, "no": 1.0 - p},
            "probability_kind": kind, "status": "complete", "abstain_reason": None, "evidence_refs": refs,
            "missing_evidence": missing or [], "gates": gates, "model": MODEL_ID,
            "catalog_version": catalog()["catalog_version"], "calibration_version": None}


def _unavailable(qid: str, dtype: str, missing: list[str], status: str = "unavailable", reason: str | None = None,
                 probs: dict | None = None) -> dict:
    return {"question_id": qid, "dtype": dtype, "value": None, "probs": probs or {},
            "probability_kind": PROB_KIND, "status": status,
            "abstain_reason": reason or (None if status != "abstained" else "insufficient evidence"),
            "evidence_refs": [], "missing_evidence": missing, "gates": {}, "model": MODEL_ID,
            "catalog_version": catalog()["catalog_version"], "calibration_version": None}


def decide(decider: ContextDecider | None, asset_id: str, img_vec: np.ndarray | None, ocr: dict | None,
           ocr_status: str, chunk_vecs: np.ndarray | None, pixels: dict | None) -> dict[str, dict]:
    cat = catalog()
    Q = cat["questions"]
    out: dict[str, dict] = {}
    regions = (ocr or {}).get("regions", []) if ocr else []
    ocr_ok = ocr_status in {"complete", "cached"}
    ocr_partial = ocr_status == "partial"
    img_ref = f"asset:{asset_id}#clip/global"
    px_ref = f"asset:{asset_id}#pixels"

    # Sufficiency heads: deterministic facts about evidence coverage.
    suff_a = bool(pixels) and img_vec is not None and ocr_ok
    out["sufficiency.a"] = _noul("sufficiency.a", 1.0 if suff_a else 0.0, [px_ref],
                                 {"pixels": bool(pixels), "clip": img_vec is not None, "ocr": ocr_status},
                                 kind="deterministic_parse")
    suff_b = img_vec is not None and (ocr_ok or not regions)
    out["sufficiency.b"] = _noul("sufficiency.b", 1.0 if suff_b else 0.0, [px_ref],
                                 {"clip": img_vec is not None, "ocr": ocr_status}, kind="deterministic_parse")

    if decider is None or img_vec is None:
        for qid, q in Q.items():
            if qid.startswith("sufficiency."):
                continue
            out[qid] = _unavailable(qid, q["type"], ["clip.global"])
        return out

    metrics = (pixels or {}).get("metrics", {})
    # -- capture_type: visual vote x documented pixel prior ------------------
    vis = decider.choice_visual(img_vec, "capture_type")
    prior = {k: 1.0 for k in vis}
    flat = metrics.get("flat_block_fraction", 0.0)
    axis = metrics.get("axis_aligned_gradient_fraction", 0.0)
    if flat >= 0.45 and axis >= 0.45:
        prior["screenshot"] *= 2.0
        prior["photo"] *= 0.5
    if (pixels or {}).get("camera_exif"):
        prior["photo"] *= 2.0
        prior["screenshot"] *= 0.5
    probs = {k: vis[k] * prior[k] for k in vis}
    z = sum(probs.values())
    probs = {k: v / z for k, v in probs.items()}
    best = max(probs, key=probs.get)
    gates = {"visual_softmax": {k: round(v, 4) for k, v in vis.items()}, "pixel_prior": prior,
             "flat_block_fraction": flat, "axis_aligned_gradient_fraction": axis}
    if probs[best] < Q["capture_type"]["abstain_below"]:
        d = _unavailable("capture_type", "choice", [], status="abstained",
                         reason=f"top option {best} below {Q['capture_type']['abstain_below']}", probs=probs)
        d["gates"] = gates
        out["capture_type"] = d
    else:
        out["capture_type"] = {"question_id": "capture_type", "dtype": "choice", "value": best, "probs": probs,
                               "probability_kind": PROB_KIND, "status": "complete", "abstain_reason": None,
                               "evidence_refs": [img_ref, px_ref], "missing_evidence": [], "gates": gates,
                               "model": MODEL_ID, "catalog_version": cat["catalog_version"],
                               "calibration_version": None}

    # -- source_app: applies to screenshots; UI evidence required per app ----
    cap = out["capture_type"]
    if cap["status"] != "complete" or cap["value"] != "screenshot":
        out["source_app"] = _unavailable("source_app", "choice", [], status="not_applicable",
                                         reason="capture_type is not a confident screenshot")
    elif not (ocr_ok or ocr_partial):
        out["source_app"] = _unavailable("source_app", "choice", ["ocr.layout"],
                                         reason="visible-UI evidence needs OCR")
    else:
        vis = decider.choice_visual(img_vec, "source_app")
        ui = ui_evidence(regions)
        required = set(Q["source_app"]["ui_evidence_required"])
        prior = {}
        for k in vis:
            if k in required:
                prior[k] = 1.0 if k in ui else LR_REQUIRED_APP_WITHOUT_UI
            else:
                prior[k] = LR_GENERIC_WHEN_APP_UI_SEEN if ui else 1.0
        probs = {k: vis[k] * prior[k] for k in vis}
        z = sum(probs.values())
        probs = {k: v / z for k, v in probs.items()}
        best = max(probs, key=probs.get)
        refs = [img_ref] + [f"asset:{asset_id}#ocr/{rid}" for rid in ui.get(best, {}).get("region_ids", [])]
        gates = {"visual_softmax": {k: round(v, 4) for k, v in vis.items()}, "ui_evidence": ui,
                 "ui_prior": prior}
        if best in required and best not in ui:
            # Hard evidence gate: a supported app is never the answer without its visible UI.
            d = _unavailable("source_app", "choice", ["ocr.layout"], status="abstained",
                             reason=f"no visible {best} UI evidence", probs=probs)
            d["gates"] = gates
            out["source_app"] = d
        elif probs[best] < Q["source_app"]["abstain_below"]:
            d = _unavailable("source_app", "choice", [], status="abstained",
                             reason=f"no option above {Q['source_app']['abstain_below']}", probs=probs)
            d["gates"] = gates
            out["source_app"] = d
        else:
            out["source_app"] = {"question_id": "source_app", "dtype": "choice", "value": best, "probs": probs,
                                 "probability_kind": PROB_KIND, "status": "complete", "abstain_reason": None,
                                 "evidence_refs": refs, "missing_evidence": [], "gates": gates,
                                 "model": MODEL_ID, "catalog_version": cat["catalog_version"],
                                 "calibration_version": None}

    # -- Noul heads -----------------------------------------------------------
    calib = load_calibration()
    text_norm = " ".join(r["norm_text"] for r in regions)
    n_words = len(text_norm.split())
    ui_any = 1.0 if (ocr_ok or ocr_partial) and ui_evidence(regions) else 0.0
    scene_p = decider.scene_probs(img_vec)
    for qid in NOUL_VISUAL:
        v = scene_p[qid] if qid in scene_p else decider.noul_visual(img_vec, qid)
        refs = [img_ref]
        gates: dict = {"visual_p": round(v, 4)}
        votes = [v]
        if qid in TEXT_HEADS_REQUIRE_OCR:
            if not (ocr_ok or ocr_partial):
                out[qid] = _unavailable(qid, "noul", ["ocr.text"], status="abstained",
                                        reason="OCR unavailable; text-dependent head not decided")
                continue
            t = decider.noul_text(chunk_vecs, qid) if regions else None
            if t is not None:
                votes.append(t)
                gates["text_p"] = round(t, 4)
                refs.append(f"asset:{asset_id}#ocr_chunks")
            elif regions:
                gates["text_p"] = None
        if qid == "context.source_code":
            cf = code_fraction(regions)
            gates["code_line_fraction"] = round(cf, 4)
            if ocr_ok or ocr_partial:
                votes.append(min(1.0, cf * 2.0))
        if qid == "context.article":
            ps = prose_score(regions)
            gates["prose_score"] = round(ps, 4)
            votes.append(ps)
        if qid == "context.film_tv_frame":
            lb = metrics.get("letterbox_top_fraction", 0) + metrics.get("letterbox_bottom_fraction", 0)
            gates["letterbox_fraction"] = round(lb, 4)  # bars alone are not a vote; see "letterbox" feature
        lex = lexicon_score(qid, text_norm)
        if qid in LEXICONS:
            gates["lexicon"] = round(lex, 4)
        letterbox = float(min(metrics.get("letterbox_top_fraction", 0), metrics.get("letterbox_bottom_fraction", 0))
                          >= 0.06)
        feats = {"letterbox": letterbox, "subtitle": subtitle_score(regions),
                 "visual_logit": _logit(v), "text_logit": _logit(gates["text_p"]) if gates.get("text_p") else 0.0,
                 "has_text": 1.0 if gates.get("text_p") else 0.0, "lexicon": lex,
                 "code_fraction": gates.get("code_line_fraction", 0.0), "prose_score": gates.get("prose_score", 0.0),
                 "ui_any": ui_any}
        gates["features"] = {k: round(x, 5) for k, x in feats.items()}
        head_cal = calib.get("heads", {}).get(qid)
        if head_cal:
            z = head_cal["bias"] + sum(head_cal["weights"].get(k, 0.0) * feats[k] for k in FEATURES)
            p = float(1 / (1 + np.exp(-z)))
            kind = "model_probability"
            gates["calibration"] = calib.get("version")
        else:
            kind = PROB_KIND
            if qid in TEXT_HEADS_REQUIRE_OCR and gates.get("text_p") is not None and n_words >= TEXT_DOMINANT_WORDS:
                votes = [gates["text_p"]] + ([lex] if qid in LEXICONS else [])
            p = float(np.mean(votes))
        d = _noul(qid, p, refs, gates, kind=kind, missing=[] if ocr_ok or qid not in TEXT_HEADS_REQUIRE_OCR
                  else ["ocr.complete_coverage"])
        if head_cal:
            d["calibration_version"] = calib.get("version")
        out[qid] = d
    return out
