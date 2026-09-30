"""Executable reference boundaries, not a replacement for AttentionX services.

No cloud calls occur unless decide() is explicitly called on a remote adapter
with cloud text permission. Extractor orchestration is in pipeline_sketch.md.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class AnalysisUnavailable(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stage_cache_key(file_hash: str, stage: str, version: str, params: Mapping[str, Any], dependencies: list[str] | None = None) -> str:
    return hashlib.sha256(canonical_json({"content_hash": file_hash, "stage": stage, "analyzer_version": version, "params": params, "dependencies": dependencies or []})).hexdigest()


def probe_asset(path: str | Path) -> dict[str, Any]:
    """Probe original bytes, before lossy normalization. No inference or decoding."""
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise ValueError("asset must be a regular managed file")
    # Worker container/OS policy supplies process/disk/memory restrictions.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)], stdout=out, stderr=err, timeout=10, check=False)
        except FileNotFoundError as exc:
            raise AnalysisUnavailable("ffprobe is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise AnalysisUnavailable("probe deadline exceeded") from exc
        if result.returncode:
            raise AnalysisUnavailable("media probe failed; inspect private worker logs")
        out.seek(0)
        raw = out.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise AnalysisUnavailable("probe metadata exceeds resource limit")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AnalysisUnavailable("probe returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("streams"), list):
        raise AnalysisUnavailable("probe returned an unexpected shape")
    return value


def build_jev_state(asset: Mapping[str, Any], focus: str = "", max_bytes: int = 16000) -> dict[str, Any]:
    """Build bounded evidence state. Select verbatim text; generate no summaries."""
    if max_bytes < 1024:
        raise ValueError("state budget is too small")
    scenes = asset.get("video_scenes", [])
    state: dict[str, Any] = {
        "target_asset": asset["asset_id"],
        "focus": focus[:256],
        "technical": asset["technical"],
        "scene_manifest": [{"scene_id": s["scene_id"], "t0": s["t0"], "t1": s["t1"], "metrics": {name: {"value": metric["value"], "confidence": metric["provenance"]["confidence"], "status": metric["provenance"]["status"]} for name,metric in s.get("metrics",{}).items()}} for s in scenes[:24]],
        "frame_manifest": [{k: s["keyframe"][k] for k in ["frame_id", "scene_id", "t", "path", "why_sampled"]} for s in scenes[:24] if s.get("keyframe")],
        "ocr_layout": [{"scene_id":s["scene_id"], "frame_id":s["keyframe"]["frame_id"] if s.get("keyframe") else None, "regions":[{k:r.get(k) for k in ["text","polygon","reading_order","language","confidence"]} for r in s.get("ocr",{}).get("value",[])]} for s in scenes[:24]],
        "audio": {key:asset["audio"][key] for key in ["loudness","silence_ranges","speech_prior"]} if asset.get("audio") else None,
        "text": [],
        "coverage": asset.get("coverage", {}),
        "evidence_availability": {"pixels_attached": False},
        "omitted_text_rows": 0,
        "omitted_scene_rows": max(0, len(scenes) - 24),
    }
    # The dispatcher builds scene/window groups first for long sources. This
    # guard rejects oversized technical state rather than silently deleting it.
    if len(canonical_json(state)) > max_bytes:
        raise AnalysisUnavailable("technical state exceeds budget; create a smaller scene group")
    rows = asset.get("text_layers", [])
    for row in rows:
        selected = {k: row.get(k) for k in ["layer_id", "t_start", "t_end", "text", "source", "conf", "source_ref"]}
        state["text"].append(selected)
        if len(canonical_json(state)) > max_bytes:
            state["text"].pop()
            state["omitted_text_rows"] += 1
    # Counter growth itself must respect the bound.
    while len(canonical_json(state)) > max_bytes and state["text"]:
        state["text"].pop()
        state["omitted_text_rows"] += 1
    if len(canonical_json(state)) > max_bytes:
        raise AnalysisUnavailable("state exceeds budget")
    return state


def normalize_answers(response: Mapping[str, Any], questions: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise AnalysisUnavailable("decision response is missing or adds question IDs")
    model = response.get("model")
    if not isinstance(model, str) or not model:
        raise AnalysisUnavailable("decision response omitted resolved model ID")
    normalized: dict[str, dict[str, Any]] = {}
    for qid, q in questions.items():
        a = answers[qid]
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            raise AnalysisUnavailable("decision response type differs from question")
        if q["type"] == "noul":
            p = a.get("noul")
            if isinstance(p, bool) or not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1:
                raise AnalysisUnavailable("invalid Noul probability")
            normalized[qid] = {"type": "noul", "value": p, "probs": {"yes": p, "no": 1-p}, "confidence": abs(2*p-1), "confidence_kind": "derived_margin", "model": model}
            continue
        probs = a.get("probabilities")
        keys = set(q["criteria"]) if q["type"] == "choice" else {str(i) for i in range(len(q["criteria"]))}
        if not isinstance(probs, dict) or set(probs) != keys:
            raise AnalysisUnavailable("unexpected decision options")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()) or abs(sum(probs.values())-1) > 1e-5:
            raise AnalysisUnavailable("invalid option probabilities")
        confidence = a.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not 0 <= confidence <= 1:
            raise AnalysisUnavailable("missing/invalid vendor confidence")
        if q["type"] == "choice":
            value = a.get("choice")
            if value not in probs or probs[value] < max(probs.values()) - 1e-5:
                raise AnalysisUnavailable("choice differs from maximum probability")
            normalized[qid] = {"type": "choice", "value": value, "probs": probs, "confidence": confidence, "confidence_kind": "vendor_statistic", "model": model}
        else:
            score = a.get("score")
            expected = sum(int(k)*v for k,v in probs.items())
            if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or abs(score-expected) > 1e-4:
                raise AnalysisUnavailable("score differs from expected level")
            # Native API levels are 0..N-1; product displays 1..N.
            normalized[qid] = {"type": "score", "value": score+1, "raw_model_score": score, "probs": {str(int(k)+1):v for k,v in probs.items()}, "legend": {str(i+1):s for i,s in enumerate(q["criteria"])}, "confidence": confidence, "confidence_kind": "vendor_statistic", "model": model}
    return normalized


class DecisionAdapter(Protocol):
    def decide(self, state: Mapping[str, Any], question_set: Mapping[str, Any], *, media: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AnalysisUnavailable("decision endpoint redirect rejected")


@dataclass(frozen=True)
class SystemOneAdapter:
    endpoint: str
    model: str
    api_key: str | None = None
    allow_cloud_text: bool = False
    allow_cloud_frames: bool = False
    timeout_s: float = 10.0

    def decide(self, state: Mapping[str, Any], question_set: Mapping[str, Any], *, media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        url = urlsplit(self.endpoint)
        local = url.hostname in {"127.0.0.1", "localhost", "::1"}
        if url.username or url.password or url.query or url.fragment or url.path != "/v1/systemone":
            raise AnalysisUnavailable("invalid configured decision endpoint")
        if local and url.scheme not in {"http", "https"}:
            raise AnalysisUnavailable("invalid local scheme")
        if not local:
            if url.hostname != "api.typesafe.ai" or url.scheme != "https" or url.port not in {None,443}:
                raise AnalysisUnavailable("remote decision endpoint is not allowlisted")
            if not self.allow_cloud_text or not self.api_key:
                raise AnalysisUnavailable("cloud text decisions are disabled or key is absent")
            # Official TypeSafe Jev is text-only. Cloud frame adapters, if later
            # added, need a distinct allowlisted provider and explicit policy.
            if media:
                raise AnalysisUnavailable("TypeSafe Jev does not accept media")
        if not 1 <= len(question_set) <= 20:
            raise ValueError("batch between 1 and 20 typed questions")
        if media and len(media) > 12:
            raise ValueError("frame group exceeds budget")
        payload: dict[str, Any] = {"model": self.model, "state": state, "questions": question_set}
        if media:
            if any(m.get("type") != "image" or not isinstance(m.get("data"),str) or not m["data"].startswith("data:image/") for m in media):
                raise ValueError("reference adapter accepts pre-extracted data-URI images only")
            payload["media"] = media
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = canonical_json(payload)
        if len(body) > 16*1024*1024:
            raise ValueError("request exceeds byte budget")
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with build_opener(_RejectRedirects()).open(request, timeout=self.timeout_s) as response:
                raw = response.read(1024*1024+1)
        except HTTPError as exc:
            # Retry scheduling, Retry-After, and bounded jitter belong to the
            # background job layer; one foreground attempt stays predictable.
            raise AnalysisUnavailable(f"decision service HTTP {exc.code}") from None
        except (URLError, TimeoutError) as exc:
            raise AnalysisUnavailable("decision service connection failed") from exc
        if len(raw) > 1024*1024:
            raise AnalysisUnavailable("decision response exceeds limit")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("response must be an object")
        except (ValueError, UnicodeError) as exc:
            raise AnalysisUnavailable("decision response is invalid JSON") from exc
        answers = normalize_answers(value, question_set)
        return {"answers": answers, "usage": value.get("usage", {}), "model": value["model"], "latency_ms": (time.monotonic()-started)*1000}


def decide(state: Mapping[str, Any], question_set: Mapping[str, Any], adapter: DecisionAdapter, *, media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return adapter.decide(state, question_set, media=media)


def frames_as_media(paths: list[Path], managed_frame_root: Path) -> list[dict[str, str]]:
    result = []
    root = managed_frame_root.resolve(strict=True)
    for p in paths:
        path = p.resolve(strict=True)
        if not path.is_relative_to(root) or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("expected a managed PNG/JPEG keyframe")
        if path.stat().st_size > 1024*1024:
            raise ValueError("keyframe exceeds upload size budget")
        mime = "image/png" if path.suffix.lower()==".png" else "image/jpeg"
        result.append({"type": "image", "data": f"data:{mime};base64,"+base64.b64encode(path.read_bytes()).decode("ascii")})
    return result


def project_ranges(scenes: list[Mapping[str, Any]], source_in: float, source_out: float, timeline_start: float = 0, playback_rate: float = 1) -> list[dict[str, Any]]:
    """Reproject cached source scenes after trim without decoding/re-analyzing."""
    if any(isinstance(v, bool) or not math.isfinite(v) for v in (source_in, source_out, timeline_start, playback_rate)) or not 0 <= source_in < source_out or playback_rate <= 0 or timeline_start < 0:
        raise ValueError("invalid source range or playback rate")
    projected = []
    for scene in scenes:
        lo, hi = max(source_in, scene["t0"]), min(source_out, scene["t1"])
        if lo < hi:
            projected.append({"scene_id":scene["scene_id"], "source_t0":lo, "source_t1":hi, "timeline_t0":timeline_start+(lo-source_in)/playback_rate, "timeline_t1":timeline_start+(hi-source_in)/playback_rate})
    return projected
