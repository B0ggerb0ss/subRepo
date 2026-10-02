"""Retrieval representations (L3a): CLIP image/text vectors, MiniLM OCR-text vectors.

These are representations, not confidences or facts. Two separate spaces:
- CLIP ViT-B-32 / laion2b_s34b_b79k (512-d): image views and text queries;
- MiniLM-L6-v2 (384-d): OCR text chunks and text queries.
Vectors are only ever compared within one namespace (same model digest and
preprocessing). Equal dimensions would not make two spaces comparable.

Image views (PREPROCESS 'clip-views/1'):
- ``global``: the whole image letterboxed (padded) to a square, then resized
  to 224, so no content is cropped away — unlike CLIP's usual center crop,
  which drops screenshot headers/footers;
- up to ``Limits.region_views_max`` region views: overlapping strips along
  the long axis for elongated images (aspect >= 1.6), else 2x2 quadrants.
  Region views let tall screenshots and crop queries match local content.

The BPE tokenizer below is a port of OpenCLIP's ``SimpleTokenizer``
(MIT License, Copyright (c) 2012-2021 Gabriel Ilharco, Mitchell Wortsman,
Nicholas Carlini, Rohan Taori, Achal Dave, Vaishaal Shankar, John Miller,
Hongseok Namkoong, Hannaneh Hajishirzi, Ali Farhadi, Ludwig Schmidt) using the
provisioned ``bpe_simple_vocab_16e6.txt.gz``.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import math
import os
import threading
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import regex as re

from services.analyze.providers import ProviderUnavailable
from services.analyze.vectors_registry import (
    CLIP_MODEL,
    CLIP_PREPROCESS,
    MINILM_MODEL,
    OCR_CHUNK_PREPROCESS,
    clip_namespace,
    minilm_namespace,
)
from services.library.config import LibraryConfig

CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
CLIP_SIZE = 224
CONTEXT_LENGTH = 77
CLIP_LOGIT_SCALE = 100.0  # OpenCLIP learned logit scale (exp(4.6052)) used for zero-shot softmax


def _ort_session(path: str):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    threads = int(os.getenv("ATTENTIONX_ORT_THREADS", "0") or 0)
    if threads:
        opts.intra_op_num_threads = threads
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return (x / np.maximum(n, 1e-12)).astype(np.float32)


# ---------------------------------------------------------------------------
# CLIP BPE tokenizer (port of open_clip.tokenizer.SimpleTokenizer)
# ---------------------------------------------------------------------------

@lru_cache()
def _bytes_to_unicode() -> dict[int, str]:
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(2 ** 8):
        if b not in bs:
            bs.append(b)
            cs.append(2 ** 8 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def _pairs(word: tuple) -> set:
    return {(a, b) for a, b in zip(word, word[1:])}


class ClipTokenizer:
    def __init__(self, bpe_path: str) -> None:
        import ftfy

        self._ftfy = ftfy
        self.byte_encoder = _bytes_to_unicode()
        merges = gzip.open(bpe_path).read().decode("utf-8").split("\n")[1:49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(_bytes_to_unicode().values())
        vocab = vocab + [v + "</w>" for v in vocab] + ["".join(m) for m in merges]
        specials = ["<start_of_text>", "<end_of_text>"]
        vocab.extend(specials)
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.bpe_ranks = dict(zip(merges, range(len(merges))))
        self.cache = {t: t for t in specials}
        self.pat = re.compile("|".join(specials) + r"""|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+""",
                              re.IGNORECASE)
        self.sot, self.eot = self.encoder["<start_of_text>"], self.encoder["<end_of_text>"]

    def _clean(self, text: str) -> str:
        text = html.unescape(html.unescape(self._ftfy.fix_text(text))).strip()
        return " ".join(text.split()).lower()

    def _bpe(self, token: str) -> str:
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = _pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new, i = [], 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                    new.extend(word[i:j])
                    i = j
                except ValueError:
                    new.extend(word[i:])
                    break
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new.append(first + second)
                    i += 2
                else:
                    new.append(word[i])
                    i += 1
            word = tuple(new)
            if len(word) == 1:
                break
            pairs = _pairs(word)
        out = " ".join(word)
        self.cache[token] = out
        return out

    def encode(self, text: str) -> list[int]:
        ids = []
        for tok in re.findall(self.pat, self._clean(text)):
            tok = "".join(self.byte_encoder[b] for b in tok.encode("utf-8"))
            ids.extend(self.encoder[t] for t in self._bpe(tok).split(" "))
        return ids

    def __call__(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        ids = np.zeros((len(texts), CONTEXT_LENGTH), dtype=np.int32)
        mask = np.zeros((len(texts), CONTEXT_LENGTH), dtype=np.int32)
        for i, t in enumerate(texts):
            toks = [self.sot] + self.encode(t) + [self.eot]
            if len(toks) > CONTEXT_LENGTH:
                toks = toks[:CONTEXT_LENGTH]
                toks[-1] = self.eot
            ids[i, :len(toks)] = toks
            mask[i, :len(toks)] = 1
        return ids, mask


# ---------------------------------------------------------------------------
# CLIP provider
# ---------------------------------------------------------------------------

def letterbox_square(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    side = max(h, w)
    fill = (CLIP_MEAN * 255).astype(np.uint8)
    canvas = np.empty((side, side, 3), dtype=np.uint8)
    canvas[:] = fill
    y0, x0 = (side - h) // 2, (side - w) // 2
    canvas[y0:y0 + h, x0:x0 + w] = rgb
    return canvas


def to_clip_tensor(rgb: np.ndarray) -> np.ndarray:
    from PIL import Image

    im = Image.fromarray(letterbox_square(rgb)).resize((CLIP_SIZE, CLIP_SIZE), Image.BICUBIC)
    x = (np.asarray(im, dtype=np.float32) / 255.0 - CLIP_MEAN) / CLIP_STD
    return x.transpose(2, 0, 1)


def plan_region_views(w: int, h: int, max_views: int) -> list[tuple[float, float, float, float]]:
    """Normalized (x0,y0,x1,y1) region views; see module docstring."""
    if max_views <= 0:
        return []
    ratio = max(w, h) / max(1, min(w, h))
    views = []
    if ratio >= 1.6:
        k = min(max_views, max(2, math.ceil(ratio)))
        span = min(1.0, 1.0 / ratio * 1.25)  # ~square windows with ~25% overlap
        starts = np.linspace(0, 1 - span, k)
        for s in starts:
            s = float(round(s, 4))
            e = float(round(min(1.0, s + span), 4))
            views.append((0.0, s, 1.0, e) if h >= w else (s, 0.0, e, 1.0))
    else:
        for y in (0.0, 0.4):
            for x in (0.0, 0.4):
                views.append((x, y, x + 0.6, y + 0.6))
        views = views[:max_views]
    return views


def crop_normalized(rgb: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = box
    xa, xb = int(round(x0 * w)), max(int(round(x1 * w)), int(round(x0 * w)) + 1)
    ya, yb = int(round(y0 * h)), max(int(round(y1 * h)), int(round(y0 * h)) + 1)
    return rgb[ya:yb, xa:xb]


class ClipProvider:
    def __init__(self, visual_path: str | None, textual_path: str, bpe_path: str) -> None:
        self._visual_path = visual_path
        self._visual = None
        self._textual = _ort_session(textual_path)
        self.tokenizer = ClipTokenizer(bpe_path)
        ns = clip_namespace()
        self.namespace = ns["namespace"]
        self.space = ns["space"]
        self.model_digest = ns["model_digest"]
        self.dim = ns["dim"]
        self._qcache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def load(cls, cfg: LibraryConfig) -> "ClipProvider":
        v = cfg.model_path(CLIP_MODEL, "visual.onnx")
        t = cfg.model_path(CLIP_MODEL, "textual.onnx")
        b = cfg.model_path(CLIP_MODEL, "bpe_simple_vocab_16e6.txt.gz")
        if not (v and t and b):
            raise ProviderUnavailable("model_missing", f"{CLIP_MODEL} not provisioned (scripts/provision_models.py)")
        try:
            return cls(str(v), str(t), str(b))
        except Exception as e:
            raise ProviderUnavailable("model_load_error", f"CLIP failed to load: {type(e).__name__}") from e

    @property
    def visual(self):
        with self._lock:
            if self._visual is None:
                self._visual = _ort_session(self._visual_path)
            return self._visual

    def encode_images(self, crops: list[np.ndarray], batch: int = 8) -> np.ndarray:
        out = []
        for i in range(0, len(crops), batch):
            x = np.stack([to_clip_tensor(c) for c in crops[i:i + batch]]).astype(np.float32)
            out.append(self.visual.run(None, {"pixel_values": x})[0])
        return _l2(np.concatenate(out))

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in texts if t not in self._qcache]
        if missing:
            ids, mask = self.tokenizer(missing)
            vecs = _l2(self._textual.run(None, {"input_ids": ids, "attention_mask": mask})[0])
            for t, v in zip(missing, vecs):
                self._qcache[t] = v
                while len(self._qcache) > 2048:
                    self._qcache.popitem(last=False)
        return np.stack([self._qcache[t] for t in texts])

    def image_views(self, rgb: np.ndarray, max_regions: int) -> list[dict]:
        h, w = rgb.shape[:2]
        regions = plan_region_views(w, h, max_regions)
        crops = [rgb] + [crop_normalized(rgb, r) for r in regions]
        vecs = self.encode_images(crops)
        views = [{"view_id": "global", "view_kind": "global_letterbox", "region": None, "vector": vecs[0]}]
        for i, (r, v) in enumerate(zip(regions, vecs[1:])):
            views.append({"view_id": f"region{i}", "view_kind": "region", "region": r, "vector": v})
        return views


# ---------------------------------------------------------------------------
# MiniLM OCR-text provider
# ---------------------------------------------------------------------------

CHUNK_TOKENS = 200
CHUNK_OVERLAP_REGIONS = 1


class MiniLMProvider:
    def __init__(self, model_path: str, tokenizer_path: str) -> None:
        from tokenizers import Tokenizer

        self.session = _ort_session(model_path)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=256)
        ns = minilm_namespace()
        self.namespace = ns["namespace"]
        self.space = ns["space"]
        self.model_digest = ns["model_digest"]
        self.dim = ns["dim"]
        self._qcache: OrderedDict[str, np.ndarray] = OrderedDict()

    @classmethod
    def load(cls, cfg: LibraryConfig) -> "MiniLMProvider":
        m = cfg.model_path(MINILM_MODEL, "model.onnx")
        t = cfg.model_path(MINILM_MODEL, "tokenizer.json")
        if not (m and t):
            raise ProviderUnavailable("model_missing", f"{MINILM_MODEL} not provisioned (scripts/provision_models.py)")
        try:
            return cls(str(m), str(t))
        except Exception as e:
            raise ProviderUnavailable("model_load_error", f"MiniLM failed to load: {type(e).__name__}") from e

    def token_count(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def encode(self, texts: list[str], batch: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tokenizer.encode_batch(texts[i:i + batch])
            L = max(len(e.ids) for e in enc)
            ids = np.zeros((len(enc), L), dtype=np.int64)
            mask = np.zeros((len(enc), L), dtype=np.int64)
            for j, e in enumerate(enc):
                ids[j, :len(e.ids)] = e.ids
                mask[j, :len(e.ids)] = e.attention_mask
            hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                             "token_type_ids": np.zeros_like(ids)})[0]
            m = mask[..., None].astype(np.float32)
            out.append((hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9))
        return _l2(np.concatenate(out)) if out else np.zeros((0, self.dim), np.float32)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in texts if t not in self._qcache]
        if missing:
            for t, v in zip(missing, self.encode(missing)):
                self._qcache[t] = v
                while len(self._qcache) > 2048:
                    self._qcache.popitem(last=False)
        return np.stack([self._qcache[t] for t in texts])

    def chunk_regions(self, regions: list[dict]) -> list[dict]:
        """Group OCR lines (reading order) into <= CHUNK_TOKENS chunks with one
        region of overlap. Every region lands in at least one chunk: a long
        screenshot becomes several chunks, never one silently truncated vector."""
        chunks: list[dict] = []
        cur: list[dict] = []
        cur_tokens = 0
        for r in regions:
            n = self.token_count(r["raw_text"]) + 1
            if cur and cur_tokens + n > CHUNK_TOKENS:
                chunks.append(self._chunk(cur, len(chunks)))
                cur = cur[-CHUNK_OVERLAP_REGIONS:] if CHUNK_OVERLAP_REGIONS else []
                cur_tokens = sum(self.token_count(x["raw_text"]) + 1 for x in cur)
            cur.append(r)
            cur_tokens += n
        if cur:
            chunks.append(self._chunk(cur, len(chunks)))
        return chunks

    @staticmethod
    def _chunk(regs: list[dict], idx: int) -> dict:
        text = "\n".join(r["raw_text"] for r in regs)
        return {"view_id": f"chunk{idx:03d}", "text": text, "region_ids": [r["region_id"] for r in regs],
                "text_sha": hashlib.sha256(text.encode()).hexdigest()[:16]}
