# F02 — Audio Extraction

## Purpose

Extract a mono WAV audio track from the normalized MP4 for use by the transcription
and audio energy analysis stages. Both F03 and F04 consume this output.

## Inputs

| Name       | Type | Description                          |
|------------|------|--------------------------------------|
| norm_path  | str  | Path to `output_norm.mp4` (from F01) |

## Outputs

| Name       | Type | Description                         |
|------------|------|-------------------------------------|
| wav_path   | str  | Path to `audio.wav` in temp dir     |

## Behavior

1. Receive `norm_path` from F01.
2. Run FFmpeg to strip video, extract audio as mono WAV at 22050 Hz.
3. Verify WAV file exists and is non-empty.
4. Return `wav_path`.

## FFmpeg Command

```bash
ffmpeg -i {norm_path} \
       -vn \
       -ar 22050 \
       -ac 1 \
       -y {wav_path}
```

- `-vn` drops the video stream
- `-ar 22050` matches librosa's default sample rate
- `-ac 1` forces mono (librosa.feature.rms requires consistent channel layout)

## Error Handling

- FFmpeg non-zero exit → raise `AudioExtractionError`
- Output WAV missing or zero-bytes → raise `AudioExtractionError`

## Constraints

- Sample rate must be 22050 Hz (librosa default, matches F04 consumption).
- Must be mono (single channel).
- Must run after F01 completes successfully.
- Output written to same temp session directory as norm_path.
