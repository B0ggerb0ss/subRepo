# Proposed analyzer and job interfaces

This file is **pseudocode**, not executable AttentionX code. Every helper below is a proposed component unless explicitly imported from `reference_interfaces.py` or named as an existing archive service. The archive does not contain this analyzer, worker, cache, asset registry, OCR adapter or Project model. Real executable boundary code is in `reference_interfaces.py`; real schema code is in `metadata_models.py`.

## 1. Scene detection with one FFmpeg decode

```python
def detect_scenes(path, probe, cfg, cache):
    key = stage_cache_key(
        file_hash=probe.source_hash,
        stage="scenes",
        version=cfg.scene_version,
        params={
            "ffmpeg_build": cfg.ffmpeg_digest,
            "stream": probe.selected_video_stream,
            "width": 320,
            "rotation": probe.rotation_recipe,
            "color": probe.color_recipe,
            "cut_threshold": cfg.cut_threshold,
            "min_separation_s": cfg.min_separation_s,
            "clock": "PTS-minus-first-presentation-time",
        },
        dependencies=[probe.cache_key],
    )
    if cache.valid(key):
        return cache.load(key)

    # Proposed bounded service: FFmpeg performs video decode/scale once.
    # Stream RGB/gray arrays with matched actual presentation timestamps.
    # Use passthrough frame timing. No fps=2 filter in the cut scan.
    # If rawvideo+showinfo is used, concurrently drain bounded stderr and
    # match showinfo frame index n to the emitted frame; never infer t=n/fps.
    previous = None
    candidates = []
    frame_summary = []
    first_pts = None
    with ffmpeg_frame_stream(path, stream=probe.selected_video_stream,
                             width=320, threads=2,
                             color_recipe=probe.color_recipe,
                             deadline=cfg.scene_deadline_s) as stream:
        for actual_pts, frame in stream:
            check_cancelled_and_resource_budget()
            first_pts = actual_pts if first_pts is None else first_pts
            t = actual_pts - first_pts
            if not finite_monotonic(t):
                raise StageFailure("INVALID_PTS")
            cheap = measure_luma_edges_and_text_prior(frame)
            # Text prior is an uncalibrated high-recall candidate signal.
            if previous is not None:
                delta = adjacent_histogram_and_content_delta(previous.frame, frame)
                candidates.append((t, delta, cheap))
            frame_summary.append_bounded_or_spooled(t, cheap)
            previous = PreviousFrame(t, frame)

    # Keep enough local neighbors to distinguish a flash from a lasting cut.
    cuts = filter_cut_candidates(candidates, cfg, frame_summary)
    boundaries = [0.0] + sorted_unique_interior(cuts) + [probe.duration_s]
    scenes = []
    for sid, (t0, t1) in enumerate(adjacent_pairs(boundaries)):
        if t1 <= t0:
            continue
        representative = choose_nonblack_sharp_interior(t0, t1, frame_summary)
        candidates = first_last_mid_and_text_change_times(t0, t1, frame_summary)
        scenes.append(ScenePlan(sid=f"s{sid}", t0=t0, t1=t1,
                                representative=representative,
                                frame_candidates=candidates,
                                cut_metrics=measured_boundary_metrics(t0)))
    result = SceneResult(scenes=scenes, actual_clock=first_pts,
                         coverage=stream.coverage, provenance=stage_provenance(key))
    cache.commit_atomic(key, result)
    return result
```

All helper names in this block are illustrative interfaces except the delivered `stage_cache_key`. Frame summaries/candidate storage must be bounded or spilled to disk, not an unbounded Python list on long media. A one-frame video receives one positive source interval only if duration is known; an image follows the image pipeline.

Extract selected frames with the same FFmpeg frame service, either retaining selected high-resolution candidates in a shared pass or using batched, bounded seeks. Verify the returned frame's PTS and record its **actual** time, not the requested seek time. First/last means meaningful frames inside `[t0,t1)`, avoiding transition frames. Keep original/display transform and inverse OCR-coordinate mapping. Normalize source-clock times against the first presentation time and retain the original origin for rendering.

Full analysis schedules first/last-per-scene plus changing text and selected stills/posters; preview schedules up to eight OCR frames per minute (configurable twelve). If scene count exceeds this, mark deferred candidate coverage and queue completion. A preview cap is not evidence that omitted scenes contain no text. Motion judgments need consecutive times/measurements, not just a representative still.

## 2. Warmed, language-aware OCR

```python
def ocr_frames(frame_refs, cfg, model_pool, cache):
    results, errors, deferred = {}, [], []
    # Provisioning happens before the job, never a hidden network download.
    recognizer = model_pool.get_ocr_if_provisioned(
        engine=cfg.ocr_engine, language_profile=cfg.ocr_languages,
        detector_digest=cfg.ocr_detector_digest,
        recognizer_digest=cfg.ocr_recognizer_digest,
    )
    if recognizer is None:
        recognizer = installed_tesseract_for_all_required_languages(cfg)
    if recognizer is None:
        return OCRResult(status="missing", errors=["OCR_MODEL_UNAVAILABLE"])

    for ref in frame_refs:
        check_cancelled_and_resource_budget()
        forced = ref.is_still or ref.is_poster or ref.user_selected or ref.scene_bound
        if not forced and ref.text_prior < cfg.text_prior_threshold:
            results[ref.id] = skipped_ocr("LOW_TEXT_PRIOR", proxy=ref.text_prior)
            continue
        if preview_budget_exhausted():
            deferred.append(ref.id)
            continue
        key = stage_cache_key(ref.pixel_hash, "ocr", cfg.ocr_version,
                              {"model_digests": recognizer.digests,
                               "language_profile": cfg.ocr_languages,
                               "long_edge": 1280,
                               "orientation": ref.orientation_recipe,
                               "layout_version": cfg.layout_version},
                              dependencies=[ref.cache_key])
        if cache.valid(key):
            results[ref.id] = cache.load(key)
            continue
        try:
            image, inverse_transform = managed_image_at_long_edge(ref, 1280)
            raw = recognizer(image)  # RapidOCR current result-object adapter
            # Do not assume old `(list, elapsed)` examples match the pinned API.
            regions = normalize_engine_regions(raw, inverse_transform)
            # Preserve literal text, raw polygon, confidence and granularity.
            # Apply NFC only under a declared text-normalization policy.
            ordered = geometric_reading_order(regions, script=cfg.ocr_languages)
            value = observation(ordered, source_modality="image",
                                extractor=recognizer.identity,
                                confidence_kind="raw_recognizer",
                                cost_class="cpu_ocr", key=key)
            cache.commit_atomic(key, value)
            results[ref.id] = value
        except RecognizerFailure:
            errors.append(sanitized_error("ocr", "OCR_FAILED", ref.id))
    return OCRResult(results=results, errors=errors, deferred=deferred,
                     status="partial" if errors or deferred else "complete")
```

Empty successful OCR is an empty observation; missing/failed/skipped OCR is a different status. A skipped text-prior result cannot support a trustworthy negative `has_on_screen_text` decision. Engine line confidence stays line confidence; never manufacture per-word values. Reconstruct columns/RTL from geometry, not string sorting. Deduplicate byte-identical frames; near-duplicate OCR reuse requires tested geometry/content tolerances and explicit coverage. Track recurring text only over observed times, leaving unsampled intervals uncertain.

## 3. Asset orchestration

```python
def analyze_asset(path, cfg, registry, cache, model_pool, progress):
    cfg = validated_job_snapshot(cfg)
    asset = registry.admit_copy_hash(path, limits=cfg.import_limits)
    # Unknown/rejected type raises AdmissionError before a metadata job exists.
    # An admitted known family may still fail decoding; preserve no fake facts.
    metadata = empty_metadata_for(asset, cfg)  # required envelopes/statuses
    planned = applicable_enabled_stages(asset.family, cfg)

    def stage(name, params, upstream_keys, run):
        if name not in planned:
            metadata.stage_status[name] = (
                "skipped" if modality_supports(name, asset.family) else "not_applicable"
            )
            return None
        key = stage_cache_key(asset.hash, name, cfg.stage_version(name),
                              params, upstream_keys)
        if cache.valid(key):
            result = cache.load(key)
            metadata.stage_status[name] = result.status
            progress.cached(name)
            return result
        progress.running(name)
        try:
            check_cancelled_and_resource_budget()
            result = run()
            result = validate_stage_result_and_provenance(result, key)
            cache.commit_atomic(key, result)
            metadata.stage_status[name] = result.status
            progress.completed(name, elapsed_and_resource_usage())
            return result
        except (MissingCapability, StageFailure, DeadlineExceeded) as exc:
            # Record sanitized stage/source/code/retryable fields.
            # Never write a fake empty success, zero quality or invented text.
            metadata.stage_status[name] = "missing" if missing(exc) else "error"
            metadata.errors.append(stage_error(name, exc, asset.id))
            metadata.partial = True
            progress.failed(name, safe_error_code(exc))
            return None

    technical = stage("probe", cfg.probe_params, [],
                      lambda: normalized_original_probe(asset))
    if technical:
        metadata.technical = technical
        if asset.family == "video":
            scenes = stage("scenes", cfg.scene_params, [technical.key],
                           lambda: detect_scenes(asset.path, technical, cfg, cache))
            if scenes:
                frames = selected_managed_frames(asset, scenes, cfg)
                metadata.video_scenes = scene_rows_with_explicit_empty_statuses(scenes)
                stage("pixel_metrics", cfg.pixel_params, frames.keys,
                      lambda: shared_image_metrics(frames, cfg))
                if cfg.ANALYSIS_OCR:
                    ocr = stage("ocr", cfg.ocr_params, frames.keys,
                                lambda: ocr_frames(frames, cfg, model_pool, cache))
                    attach_actual_ocr_and_single_frame_text_layers(metadata, ocr)
        elif asset.family == "image":
            metadata.image = stage("image", cfg.image_params, [technical.key],
                                   lambda: pillow_and_shared_pixel_observations(asset))
            if cfg.ANALYSIS_OCR and metadata.image is not None:
                stage("ocr", cfg.ocr_params, [metadata.image.key],
                      lambda: ocr_frames([managed_still_ref(asset)], cfg, model_pool, cache))

        if has_admitted_audio_stream(technical):
            audio = stage("audio", cfg.audio_params, [technical.key],
                          lambda: original_channel_audio_observations(asset, cfg))
            attach_audio(metadata, audio)
            if audio is not None and cfg.ANALYSIS_ASR and (cfg.captions_requested or speech_route(audio, cfg)):
                asr = stage("asr", cfg.asr_params, [audio.key],
                            lambda: warmed_asr_on_16k_mono(asset, model_pool, cfg))
                attach_original_clock_asr_and_diagnostics(metadata, asr)
        if asset.family == "text":
            stage("text", cfg.text_params, [technical.key],
                  lambda: parse_srt_vtt_or_plain_text(asset, cfg))

    # Backend selection is constrained by privacy before any remote call.
    adapters = choose_enabled_backends(cfg, provisioned=model_pool.capabilities)
    for group in build_explicitly_targeted_groups(metadata, cfg.focus):
        applicable = filter_question_evidence_gates(group, metadata)
        record_skipped_question_reasons(metadata, group, applicable)
        if not applicable:
            continue
        # <=20 questions; <=12 images; state<=16k UTF-8 bytes.
        state = build_jev_state(group.asset_view, cfg.focus, max_bytes=16000)
        media = None
        if group.requires_pixels:
            if not cfg.ANALYSIS_ONEJEV or not adapters.local_vision:
                record_unavailable_pixel_decisions(metadata, group)
                continue
            media = frames_as_media(group.paths, registry.managed_frame_root)
            state = link_actual_frame_ids_times_and_image_markers(state, group)
            state["evidence_availability"]["pixels_attached"] = True
            adapter = adapters.local_vision
        else:
            adapter = adapters.text
        if adapter is None:
            record_skipped_semantic_stage(metadata, group)
            continue
        stage("decisions", group.catalog_and_backend_params,
              group.all_evidence_keys,
              lambda: decide(state, applicable, adapter, media=media))

    attach_all_stage_results_and_control_provenance(metadata)
    metadata.search_tags = project_tags_with_evidence_and_probability_threshold(metadata, .65)
    enforce_review_if_low_or_incomplete_coverage(metadata)
    metadata.partial |= scheduled_stage_failed_or_budget_truncated(metadata)
    metadata.analyzed_at = current_utc_timestamp()
    validated = MediaMetadata.model_validate(metadata)
    sidecar_ref = registry.commit_metadata_atomic(asset.id, validated)
    registry.publish_if_current(asset.id, cfg.revision_fence, sidecar_ref)
    return validated
```

This orchestration shows dependencies and recovery, not an implementation to paste into a production file. Result attachment and stage-specific data types are abstract. `normalized_original_probe` selects ffprobe for video/audio, Pillow for a still, and bounded decoding/parsing for text; it must not call ffprobe on SRT. If a required probe fails, the job returns a diagnostic partial envelope for the admitted family without fabricated probe facts. `analyze_asset` raises for admission rejection or a failed final persistence/validation transaction; it must not claim a saved result.

Audio original-layout EBU R128/true peak/silence measurements precede ASR downmix. Silence gives null undefined LUFS, not infinity. Heuristic speech prior is a routing signal, not a semantic certainty. Caption requests enable ASR explicitly; music-only beds are not transcribed by default. All configured stage dependencies include model/build versions and extraction parameters. Cache-hit producer provenance stays unchanged; per-run telemetry records cached cost rather than rewriting the original measurement identity.

## 4. Worker, trim and failure rules

Use one spawned Python media worker initially, with a warmed OCR/ASR pool and a bounded FFmpeg process runner. UI callbacks enqueue IDs/config snapshots and poll snapshots; they do not await a long analyzer in the UI process. Models/frames are not in `gr.State`. Never dispatch raw arbitrary filesystem paths or executable project instructions.

Each stage uses a lease/key and atomic write so worker restart cannot publish a half JSON file. A UI update checks project/clip revision; an old result can enter the immutable cache but cannot replace newer focus/trim context. Timeout/cancellation kills the FFmpeg process group if cooperative termination fails, and deletes only disposable work. Distinguish permanent 401/422/schema errors from transient 429/529/timeouts; retry transient model calls at most twice within the job deadline, honoring Retry-After and jitter. No retry switches to cloud or another language/model silently.

A trim first calls real `project_ranges` with immutable source scenes; it intersects text/silence similarly. Reuse source OCR/ASR and any in-range representative. Extract one new frame only if needed; recompute only selected-range loudness and editorial context. Crops/overlays/speed/audio effects have derivative recipe keys. LUFS cannot be averaged from independent full-source values. A project order/focus edit invalidates context decisions, not source extraction.

Admission/resource limits, FFmpeg local protocol allowlists, managed paths, model provisioning and per-user ownership are production boundary requirements, not all implemented by the reference functions. No uploaded fonts install to shared directories, no media URL redirects, no raw video leaves the local worker, and local-only blocks cloud text as well as cloud pixels.
