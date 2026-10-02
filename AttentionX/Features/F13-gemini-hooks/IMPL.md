# F13 — Gemini Hook Generation — Implementation

## File Location

`services/gemini_hooks.py`

## Dependencies

- `os` (stdlib)
- `json` (stdlib)
- `google.generativeai` — lazy import (not at module level)
- `models/schemas.py` — `ScoredSegment`

## Core Function Signature

```python
def generate_hook(scored_seg: ScoredSegment, clip_index: int) -> tuple[str, str]:
    """
    Generate hook headline and summary using Gemini API.
    Returns ("", "") if API key absent or any error occurs.
    Never raises.
    """
```

## Implementation

```python
import os
import json

def generate_hook(scored_seg, clip_index):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "", ""
    
    try:
        import google.generativeai as genai   # lazy import
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        transcript = scored_seg.candidate.transcript_text[:800]  # cap token input
        prompt = (
            "You are a short-form video editor. Given a transcript excerpt, produce:\n"
            "1. A hook headline in 10 words or fewer.\n"
            "2. One sentence explaining why this moment is compelling.\n\n"
            f"Transcript:\n{transcript}\n\n"
            'Respond in JSON: {"hook": "...", "summary": "..."}'
        )
        
        response = model.generate_content(prompt)
        data = json.loads(response.text)
        hook    = str(data.get("hook", ""))[:80]      # hard cap
        summary = str(data.get("summary", ""))[:200]  # hard cap
        return hook, summary
    
    except Exception:
        return "", ""
```

## Integration in app.py

```python
from services.gemini_hooks import generate_hook

# after rendering each clip:
hook, summary = generate_hook(seg, i)
# display hook and summary in gr.Markdown or gr.Textbox next to the clip
```

## Notes

- `[:800]` on transcript caps the prompt to roughly 200 tokens, staying within free-tier limits.
- Lazy import (`import google.generativeai as genai` inside the function) means the module
  does not need to be installed for the pipeline to run — `requirements.txt` lists it as optional.
- Hard cap on hook (80 chars) and summary (200 chars) prevents malformed API responses
  from leaking into the UI as giant text blobs.
- `gemini-1.5-flash` is the free-tier model as of the knowledge cutoff; update model name
  if Gemini API changes the free-tier offering.
