import importlib.metadata
import os
import sys
import time
from pathlib import Path

from .core import Failure, asr_config, atomic_json, file_hash, fingerprint, media_dir, read_json, validate_segments, model_config


def funasr_segments(results):
    segments = []
    for item in results or []:
        sentences = item.get("sentence_info") or []
        if sentences:
            for s in sentences:
                text = str(s.get("text") or "").strip()
                if text:
                    segments.append({"start": float(s.get("start") or 0) / 1000,
                                     "end": float(s.get("end") or s.get("start") or 0) / 1000, "text": text})
            continue
        text = str(item.get("text") or "").strip()
        ts = item.get("timestamp") or []
        if text:
            # Do not invent sentence/word alignment. Explicitly use a coarse span.
            segments.append({"start": float(ts[0][0]) / 1000 if ts else 0,
                             "end": float(ts[-1][1]) / 1000 if ts else 0, "text": text})
    segments.sort(key=lambda s: s["start"])
    validate_segments(segments)
    return segments


def classify_error(exc):
    text = str(exc).lower()
    if "out of memory" in text or "cuda_error_out_of_memory" in text:
        return "gpu_oom"
    if any(k in text for k in ("cuda", "cudnn", "cublas", "driver", "libcud", "nvidia")):
        return "gpu_unavailable"
    return "asr_failed"


def model_lock(engine):
    root = Path(os.getenv("MODEL_ROOT", "/models"))
    lock = read_json(root / "models.lock.json", {})
    record = lock.get(engine)
    if not record:
        raise Failure("asr_failed")
    # Validate content on every child startup. Changed weights cannot reuse a cached transcript.
    for label, model in record["models"].items():
        path = (root / model["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_dir():
            raise Failure("invalid_artifact")
        inventory = {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob("*")) if p.is_file()}
        if fingerprint(inventory) != model["content_hash"]:
            raise Failure("invalid_artifact")
    return root, record


def infer(directory, engine):
    config = asr_config(engine)
    source_dir = media_dir(directory)
    media = read_json(source_dir / "media.json")
    audio = source_dir / "audio.wav"
    if not media or not audio.exists() or file_hash(audio) != media.get("audio_sha256"):
        raise Failure("invalid_artifact")
    root, lock = model_lock(engine)
    if model_config(lock["config"]) != model_config(config):
        raise Failure("invalid_artifact")
    started = time.monotonic()
    if engine == "whisper":
        import ctranslate2
        from faster_whisper import WhisperModel
        if ctranslate2.get_cuda_device_count() < 1:
            raise Failure("gpu_unavailable")
        model = WhisperModel(str(root / lock["models"]["asr"]["path"]), device="cuda", compute_type=config["compute_type"],
                             local_files_only=True)
        iterator, info = model.transcribe(str(audio), language=None, beam_size=config["beam_size"], vad_filter=True)
        segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in iterator if s.text.strip()]
        actual = {"engine": engine, "device": model.model.device, "compute_type": model.model.compute_type,
                  "language": info.language, "language_probability": info.language_probability,
                  "packages": {p: importlib.metadata.version(p) for p in ("faster-whisper", "ctranslate2")}}
        if actual["device"] != "cuda" or actual["compute_type"] != config["compute_type"]:
            raise Failure("gpu_unavailable")
    else:
        import torch
        from funasr import AutoModel
        if not torch.cuda.is_available():
            raise Failure("gpu_unavailable")
        models = lock["models"]
        model = AutoModel(model=str(root / models["asr"]["path"]), vad_model=str(root / models["vad"]["path"]),
                          punc_model=str(root / models["punc"]["path"]), device="cuda", disable_update=True,
                          disable_pbar=True, trust_remote_code=False)
        parameters = list(model.model.parameters())
        if not parameters or any(p.device.type != "cuda" for p in parameters):
            raise Failure("gpu_unavailable")
        dtype = str(parameters[0].dtype).split(".")[-1]
        if dtype != config["compute_type"]:
            raise Failure("invalid_artifact")
        components = {}
        for label, component in (("asr", model.model), ("vad", model.vad_model), ("punctuation", model.punc_model)):
            ps = list(component.parameters()) if component is not None else []
            components[label] = {"devices": sorted({p.device.type for p in ps}), "dtypes": sorted({str(p.dtype) for p in ps})}
            if ps and any(p.device.type != "cuda" for p in ps):
                raise Failure("gpu_unavailable")
        hints = directory / "asr-hotwords.txt"
        hints.write_text("\n".join(config["hotwords"]) + "\n", encoding="utf-8")
        result = model.generate(input=str(audio), batch_size_s=config["batch_size_s"],
                                hotword=str(hints), sentence_timestamp=True)
        torch.cuda.synchronize()
        segments = funasr_segments(result)
        actual = {"engine": engine, "device": "cuda", "compute_type": dtype, "language": "zh",
                  "gpu_name": torch.cuda.get_device_name(0), "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                  "components": components,
                  "packages": {p: importlib.metadata.version(p) for p in ("torch", "torchaudio", "funasr")}}
    try:
        validate_segments(segments)
    except Failure as exc:
        atomic_json(directory / "asr-failure.json", {"error": exc.code, "actual": actual, "config": config,
                    "duration_s": time.monotonic() - started, "model_lock_hash": fingerprint(lock)})
        raise
    cache_key = fingerprint({"media": media["sha256"], "audio": media["audio_sha256"], "config": config,
                             "weights": fingerprint(lock)})
    result = {"segments": segments, "actual": actual, "config": config, "model_lock_hash": fingerprint(lock),
              "cache_key": cache_key, "duration_s": time.monotonic() - started}
    atomic_json(directory / "raw.json", result)
    return result


def main():
    role, dirname, request_name, result_name = sys.argv[1:]
    directory, result_path = Path(dirname), Path(result_name)
    try:
        payload = read_json(Path(request_name))
        if role == "download":
            from .download import download_task
            data = download_task(directory, payload["url"], bool(payload.get("want_video")))
        else:
            data = infer(directory, payload["engine"])
        atomic_json(result_path, data)
    except Failure as exc:
        atomic_json(result_path, {"error": exc.code})
        return 1
    except Exception as exc:
        atomic_json(result_path, {"error": classify_error(exc) if role == "gpu" else "download_failed",
                                 "exception_type": type(exc).__name__})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
