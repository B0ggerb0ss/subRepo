# Verification record — 30 September 2026

This record separates observations from design targets. No live model service, real OCR/ASR/OneJev inference, hosted UI or deployment was used. Original source files were not modified.

| Check | Observed result | Scope |
|---|---|---|
| Original ZIP inventory | 267 entries: 201 files, 66 directory entries; 24,468,026 uncompressed bytes | Original paths, role, bytes, SHA-256 in CSV/JSON |
| Python source review | All 51 original `.py` files read and AST-parsed | Includes 20 runtime files, 13 scripts, 18 test files |
| Documentation/config/tooling review | All 57 Markdown files, requirements/packages, both shell scripts and fixture JSON reviewed | Developer docs can describe proposed behavior; source determines current functionality |
| Existing Gates 7 and 8 | Passed, 3 checks each | Current scorer/ranking and caption small contracts; not model accuracy |
| Synthetic actual FFmpeg path | Normalize H.264/AAC, extract mono 22,050-Hz WAV, render 720×1280 H.264/AAC succeeded | Requested 1.5s range produced 1.625s container; exact seek/content-sync not established |
| Current-code defect reproductions | Caption loss/overflow, snap duration, silence gap, face-mask/crop mean, narrow crop failure and capitalization bias observed | Detailed values in `reproductions.json` |
| Proposed schema/example | Pydantic validation succeeded; JSON Schema regenerated from final models | Example is explicitly illustrative, not analyzed evidence |
| Proposed offline reference suite | **10 tests, 10 passed**; latest run 0.125s (wall time is not an analysis benchmark) | No external inference; real ffprobe source fixture included in this audit run |
| Full original pytest suite | **Not run** | pytest and core runtime libraries absent; temporary dependency installation blocked by network access |
| Native compatibility / OCR CER / ASR WER / semantic calibration | **Not measured** | Requires pinned dependencies, provisioned models, intended hardware and held-out labels |
| Browser UI / multi-user / deployment | **Not run** | UI integration and worker isolation are proposed implementation work |

Offline reference checks cover complete schema loading; invalid probabilities/source ranges/failed-stage completion/frame paths/score levels; native zero-based score conversion and separate confidence; malformed provider shapes; trim speed/time projection without source mutation; cache dependency/version/parameter keys; bounded layout-aware state without pretending to see pixels; blocked cloud/no-key/media calls before network; required catalog groups/options; and original sample ffprobe.

The standalone ZIP omits original media. Its optional source-fixture probe test skips if the original extracted repository is unavailable; the other nine tests remain runnable with Pydantic v2. The audit execution used Python 3.12.14, Pydantic 2.13.5 and NumPy 2.3.5. The archive declares NumPy `<2`, so focused tests here do not certify the intended native stack. FFmpeg and ffprobe were installed; Gradio, faster-whisper, librosa, MediaPipe, PySceneDetect, OpenCV, pytest and jsonschema were absent.

No latency/accuracy/cost numbers in the design are measured model results. Budgets, CER/WER/F1/ECE thresholds and the 45-second JSON values are clearly labeled targets or illustrations. Cost arithmetic uses published input-only Jev pricing, not a paid request. The source and local fixtures were not uploaded to an inference provider.
