# F13 — Gemini Hook Generation — Validation

## Validation Context

F13 is optional and non-blocking. It has no associated Gate.
Validation verifies it enhances without breaking.

## Pass Criteria

```
API key absent → ("", "") returned, no exception            ✓
API key present → (hook_text, summary) returned             ✓
hook_text <= 80 characters                                  ✓
summary <= 200 characters                                   ✓
Any API exception → ("", "") returned, no propagation       ✓
Pipeline completes with all hook fields empty (key absent)  ✓
generate_hook never raises                                  ✓
```

## Test Cases

### TC-01: No API key

```
Input:    GEMINI_API_KEY not set in environment
Expected: generate_hook() returns ("", "")
          No ImportError for google.generativeai
          No exception propagated
```

### TC-02: Valid API key and transcript

```
Input:    GEMINI_API_KEY=valid_key, scored_seg with 50-word transcript
Expected: hook_text is a string of <= 10 words
          summary is a single sentence
          Both non-empty
```

### TC-03: API timeout or network error

```
Input:    GEMINI_API_KEY set, but network unavailable
Expected: generate_hook() returns ("", "")
          Exception caught, not propagated
```

### TC-04: Malformed API response (non-JSON)

```
Input:    Mocked API response returns plain text instead of JSON
Expected: json.loads fails → generate_hook() returns ("", "")
          No exception propagated
```

### TC-05: Long transcript input

```
Input:    scored_seg with transcript_text of 2000 characters
Expected: generate_hook() sends only first 800 characters to API
          No token limit error from Gemini
```

### TC-06: Full pipeline without key

```
Input:    Run complete pipeline from upload to download with no GEMINI_API_KEY
Expected: All clips rendered and downloadable
          Hook fields in UI are empty strings
          No warning or error shown to user about missing Gemini key
```

## Manual Verification

- [ ] Set `GEMINI_API_KEY` in environment and run the app
- [ ] Upload a video and generate clips
- [ ] Confirm hook text appears next to clip in the UI
- [ ] Confirm hook is ≤ 10 words and sounds relevant to the clip content
- [ ] Unset `GEMINI_API_KEY` and regenerate — confirm hooks disappear silently
