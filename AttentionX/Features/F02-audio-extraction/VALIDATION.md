# F02 — Audio Extraction — Validation

## Gate 2 Contribution

This feature completes Gate 2 alongside F01.

## Test Cases

### TC-01: Happy path

```
Input:    valid output_norm.mp4 from F01
Expected: audio.wav exists, non-zero size
          ffprobe audio.wav → sample_rate=22050, channels=1
```

### TC-02: Input video with no audio

```
Input:    norm.mp4 with no audio stream
Expected: AudioExtractionError raised with clear message
```

### TC-03: WAV file verifiable with librosa

```
Input:    audio.wav from TC-01
Expected: librosa.load(wav_path, sr=22050) succeeds
          y.shape[0] > 0
          sr == 22050
```

## Pass Criteria Summary

```
audio.wav exists and non-zero                     ✓
ffprobe: sample_rate=22050                        ✓
ffprobe: channels=1                               ✓
librosa.load() succeeds on the WAV               ✓
AudioExtractionError on missing audio stream      ✓
```
