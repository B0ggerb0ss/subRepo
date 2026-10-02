# F03 — Speech Transcription — Validation

## Gate 3 Pass Criteria

```
Non-empty TranscriptSegment list returned          ✓
start < end for every segment                      ✓
timestamps monotonically increasing                ✓
3+ sampled phrases manually verified vs audio      ✓ (manual)
TranscriptionError raised for silent audio         ✓
```

## Test Cases

### TC-01: Clear spoken audio

```
Input:    audio.wav with 30–60s of clear speech
Expected: >= 3 segments returned
          Each segment: start < end, text non-empty
          Sample 3 phrases — match audio on listening review
```

### TC-02: Silent audio

```
Input:    audio.wav with no speech (silence or music only)
Expected: TranscriptionError raised with "no speech detected"
```

### TC-03: Timestamp monotonicity

```
Input:    any multi-segment transcript result
Expected: segments[i].end <= segments[i+1].start for all i
          (minor overlaps acceptable; hard reversals are not)
```

### TC-04: Model size config

```
Input:    model_size="small"
Expected: transcription completes without error
          Result quality subjectively better than "base" on the same audio
```

## Manual Verification Checklist

- [ ] Print all segments to console
- [ ] Listen to source audio at 3 random timestamps
- [ ] Confirm segment text matches what is spoken at those timestamps
- [ ] Confirm no segment has empty `text` field
- [ ] Confirm `start` and `end` times are in seconds (not frames or milliseconds)
