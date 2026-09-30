# ADR-010 — Resolving the conflict with `SPECs/agent.md`

`SPECs/agent.md` (prototype era) forbids persistent storage/databases, requires temp-only writes and single public deployment, and caps modules ("prefer editing existing files"). The authorized request is a *persistent local media library*.

**Decision.** `SPECs/agent.md` is updated: the video clip pipeline keeps its constraints (single process, ephemeral session temp/output, Gemini optional, face fallback), and a new **Image library** section authorizes a local SQLite library under managed roots, loopback binding by default, no deployment/publishing, no cloud fallback, no automatic source deletion. The "one pipeline, one process" directive is kept for the video path; the library adds one local worker process, not a microservice split.
