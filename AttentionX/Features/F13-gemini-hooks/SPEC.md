# F13 — Gemini Hook Generation (Optional)

## Purpose

For each rendered clip, optionally generate a short hook headline (≤ 10 words) and
a one-sentence summary explaining why the clip was selected. Displayed in the UI
alongside the clip preview. Improves demo polish for judges.

This feature is strictly optional and must never be on the critical pipeline path.

## Inputs

| Name          | Type          | Description                                 |
|---------------|---------------|---------------------------------------------|
| scored_seg    | ScoredSegment | Contains transcript_text and score_breakdown |
| clip_index    | int           | For labeling in the response                |

## Outputs

| Name        | Type  | Description                                   |
|-------------|-------|-----------------------------------------------|
| hook_text   | str   | ≤ 10 word hook headline, or "" if unavailable |
| summary     | str   | One-sentence explanation, or "" if unavailable |

## Behavior

1. Check for `GEMINI_API_KEY` in environment. If absent → return `("", "")`.
2. Build a text prompt using `scored_seg.candidate.transcript_text` (transcript only, never video).
3. Call Gemini API (`gemini-1.5-flash` or equivalent free-tier model).
4. Parse response into `(hook_text, summary)`.
5. Return results.
6. On any API error → return `("", "")` (never propagate exception).

## Prompt Template

```
You are a short-form video editor. Given a transcript excerpt, produce:
1. A hook headline in 10 words or fewer that would grab attention.
2. One sentence explaining why this moment is compelling.

Transcript:
{transcript_text}

Respond in JSON: {"hook": "...", "summary": "..."}
```

## Error Handling

- `GEMINI_API_KEY` absent → return `("", "")` immediately
- API call raises any exception → return `("", "")`, log warning
- JSON parse fails → return `("", "")`, log warning
- Response missing fields → return `("", "")`, log warning

## Constraints

- MUST be wrapped in `try/except Exception` at the outermost level.
- MUST NOT be imported unconditionally — use lazy import inside the function.
- NEVER send raw video bytes to Gemini — text-only input.
- NEVER make this function a required step in the pipeline.
- Free tier only; do not configure billing or paid endpoints.
