# ADR-001 — AttentionX lives in `subRepo/AttentionX/`

**Status:** accepted (2026-09-30)

**Context.** The designated branch belongs to `B0ggerb0ss/subRepo`, which only held an unrelated HTML stub. The AttentionX source existed solely in the uploaded ZIP; its own `.git` tracked only `.gitignore`/`README.md` (every runtime file untracked — confirming the audit's deployment finding).

**Decision.** Import the archive's working tree verbatim into `AttentionX/` as its own commit (`Import AttentionX source … (unmodified)`), excluding `.git`, caches, runtime `data/temp`/`data/outputs` and media binaries. All changes follow as separate commits.

**Alternatives.** Import at repo root (mixes with the unrelated stub); reuse the archived `.git` (would carry no history of the runtime files anyway).

**Consequences.** All paths in the docs are relative to `AttentionX/`. Test media are generated (`tests/support/media_factory.py`), so no binaries were lost. `deploy_to_hf.sh` still pushes `HEAD` — not run; deployment is out of scope.

**Validation.** `git show --stat` of the import commit lists only archive files; the original test suite passed unchanged there (26 passed, with `faster-whisper` installed).
