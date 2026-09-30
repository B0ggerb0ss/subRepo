# F04 — Audio Energy Analysis — Validation

## Gate 4 Pass Criteria

```
Non-empty RMSCurve returned                        ✓
times and values arrays have equal length           ✓
values all in [0, 1]                               ✓
At least one EnergyPeak identified on speech audio ✓
Peak timestamps overlap audibly emphatic moments   ✓ (manual)
Empty peak list on silent audio (no exception)     ✓
```

## Test Cases

### TC-01: Normal speech audio

```
Input:    audio.wav with spoken content
Expected: rms_curve.times non-empty
          rms_curve.values all in [0.0, 1.0]
          len(energy_peaks) >= 1
```

### TC-02: Energy peak alignment

```
Input:    audio.wav with a known loud passage (e.g., shouting or emphasis)
Expected: at least one EnergyPeak overlaps the known loud passage
          Verify by comparing peak.start and peak.end against listening test
```

### TC-03: Silent audio

```
Input:    audio.wav that is pure silence
Expected: energy_peaks = []  (empty list, no exception)
          rms_curve returned with all-zero values
```

### TC-04: Score normalization

```
Input:    any audio.wav
Expected: max(rms_curve.values) <= 1.0
          min(rms_curve.values) >= 0.0
```

### TC-05: Merge gap behavior

```
Input:    audio with two emphatic moments 0.3 seconds apart
Expected: merged into a single EnergyPeak (gap < 0.5s threshold)
```

## Manual Debug Checklist

- [ ] Print first 10 (time, rms) pairs — values should be in [0, 1]
- [ ] Print all EnergyPeak objects — timestamps in seconds
- [ ] Listen to source audio at peak.start for 3 peaks — confirm audible emphasis
- [ ] Confirm no peak has start >= end
