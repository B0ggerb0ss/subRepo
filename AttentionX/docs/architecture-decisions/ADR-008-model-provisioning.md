# ADR-008 — Explicit provisioning and model substitutions

**Decision.** `docs/model-manifest.json` pins every artifact (URL, size, sha256, upstream md5, license, language/taxonomy/preprocessing scope). `scripts/provision_models.py` is the only network path for models; it verifies hashes and writes `PROVISIONED.json`. Analysis/search never download; a missing model is a visible capability state.

| Role | Prompt suggestion | Provisioned | Why |
|---|---|---|---|
| image-text | OpenCLIP ViT-B-32 / laion2b_s34b_b79k | same, ONNX export (Jina clip-as-service S3, md5-verified) | HF blocked; torch not needed |
| OCR text | all-MiniLM-L6-v2 | same, ONNX (Qdrant fastembed GCS, md5-verified) | HF blocked |
| objects | torchvision SSDlite320 COCO_V1 | **EfficientDet-Lite0** (MediaPipe, COCO labels from model metadata) | download.pytorch.org blocked; same role/taxonomy class |
| faces (legacy) | MediaPipe | BlazeFace short-range (MediaPipe Tasks) | legacy API absent |
| OCR | RapidOCR PP-OCR | rapidocr_onnxruntime 1.4.4 bundled PP-OCRv4 | in-wheel weights |
| decisions | OneJev | **not provisioned** → ADR-005 | GitHub/HF blocked |
| ASR | faster-whisper | library only, **weights not provisioned** | HF blocked |

Native dependency discovered: MediaPipe Tasks needs `libEGL.so.1` (`libegl1`, now in `packages.txt`).
