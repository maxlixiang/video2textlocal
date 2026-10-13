"""Actual container smoke verification. No Telegram token or login state used."""
import argparse
import os
import time
import uuid
import re
from pathlib import Path

from .core import asr_config, Failure, atomic_json, file_hash, media_dir, parse_target, read_json, task_dir, validate_segments, write_transcript
from .net import json_request


def run_sample(sample, repeat, recognize=False):
    tid = uuid.uuid4().hex
    root = Path(os.getenv("DATA_ROOT", "/results"))
    row = {"label": sample["label"], "repeat": repeat, "task_id": tid, "expected": sample.get("expect", "success")}
    start = time.monotonic()
    try:
        target = parse_target(sample["input"])
        result = json_request(os.getenv("DOWNLOAD_URL", "http://download:8080") + "/run",
                              {"task_id": tid, "url": target.url}, timeout=int(os.getenv("DOWNLOAD_TIMEOUT", "600")) + 60)
        if sample.get("expected_id") and result.get("media_id") != sample["expected_id"]:
            raise Failure("target_mismatch")
        row.update(status="passed" if row["expected"] == "success" else "failed", media=result)
        # Separate ID means every repeat uses a clean browser and performs a real download.
        if not (media_dir(task_dir(root, tid)) / "audio.wav").exists():
            raise Failure("no_media")
        if recognize:
            engine = "funasr" if target.platform == "douyin" else "whisper"
            inferred = json_request(os.getenv("GPU_URL", "http://gpu:8080") + "/run", {"task_id": tid, "engine": engine, "config":asr_config(engine)},
                                    timeout=int(os.getenv("ASR_TIMEOUT", "7200")) + 60)
            validate_segments(inferred["segments"])
            if inferred["actual"]["device"] != "cuda":
                raise Failure("gpu_unavailable")
            row["asr"] = {"actual": inferred["actual"], "segments": len(inferred["segments"]), "duration_s": inferred["duration_s"]}
    except Failure as exc:
        accepted_failure = exc.code in sample.get("expected_errors", ["unavailable", "verification_required", "target_mismatch", "no_media"])
        row.update(status="passed" if row["expected"] == "failure" and accepted_failure else "failed", error=exc.code)
    diagnostics = read_json(media_dir(task_dir(root, tid)) / "douyin-diagnostics.json")
    if diagnostics:
        row["diagnostics"] = diagnostics
    row["duration_s"] = time.monotonic() - start
    return row


def gpu():
    from .download import decode_audio, probe, stream_file
    # Public speech sample linked by the official FunASR project; no synthetic tone-only test.
    url = "https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.wav"
    tid = uuid.uuid4().hex
    directory = task_dir(Path(os.getenv("DATA_ROOT", "/results")), tid)
    directory.mkdir(parents=True)
    source = media_dir(directory)
    source.mkdir(parents=True)
    staged = source / "speech.part"
    stream_file(url, staged)
    duration = probe(staged)
    wav = source / "audio.part.wav"
    decode_audio(staged, wav)
    staged.replace(source / "media.bin")
    wav.replace(source / "audio.wav")
    atomic_json(source / "media.json", {"sha256": file_hash(source / "media.bin"), "audio_sha256": file_hash(source / "audio.wav"), "duration": duration})
    output = []
    for engine in ("funasr", "whisper", "funasr"):
        try:
            result = json_request(os.getenv("GPU_URL", "http://gpu:8080") + "/run", {"task_id": tid, "engine": engine, "config":asr_config(engine)},
                                  timeout=int(os.getenv("ASR_TIMEOUT", "7200")) + 60)
            validate_segments(result["segments"])
            if result["actual"]["device"] != "cuda":
                raise Failure("gpu_unavailable")
            evidence = {"engine": engine, "status": "passed", "actual": result["actual"], "config": result["config"],
                        "model_lock_hash": result["model_lock_hash"], "segments": len(result["segments"]), "duration_s": result["duration_s"]}
            atomic_json(directory / f"{engine}-{len(output)}.json", result)
            output.append(evidence)
        except Failure as exc:
            output.append({"engine": engine, "status": "failed", "error": exc.code})
    return output


def existing(task_id, engine=None):
    directory = task_dir(Path(os.getenv("DATA_ROOT", "/results")), task_id)
    media = read_json(media_dir(directory) / "media.json", {})
    selected = engine or ("funasr" if media.get("platform") == "douyin" else "whisper")
    try:
        result = json_request(os.getenv("GPU_URL", "http://gpu:8080") + "/run", {"task_id": task_id, "engine": selected, "config":asr_config(selected)},
                              timeout=int(os.getenv("ASR_TIMEOUT", "7200")) + 60)
        validate_segments(result["segments"])
        if result["actual"]["device"] != "cuda":
            raise Failure("gpu_unavailable")
        path = directory / f"{task_id}_原稿.md"
        write_transcript(path, result["segments"], result["actual"])
        return {"task_id": task_id, "engine": selected, "status": "passed", "actual": result["actual"],
                "segments": len(result["segments"]), "duration_s": result["duration_s"], "original_sha256": file_hash(path)}
    except Failure as exc:
        return {"task_id": task_id, "engine": selected, "status": "failed", "error": exc.code}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--douyin", action="store_true")
    p.add_argument("--gpu", action="store_true")
    p.add_argument("--asr", action="store_true")
    p.add_argument("--repeat", type=int, default=2)
    p.add_argument("--existing", nargs="+")
    p.add_argument("--engine", choices=["funasr", "whisper"])
    p.add_argument("--report-name")
    p.add_argument("--samples", default="/app/samples.json")
    args = p.parse_args()
    name = "gpu" if args.gpu else "douyin" if args.douyin else "platforms"
    if args.existing:
        name = "existing-media-pipeline"
    if args.asr:
        name += "-pipeline"
    if args.report_name:
        if not re.fullmatch(r"[a-z0-9-]{1,64}", args.report_name):
            p.error("report-name must be a safe lowercase slug")
        name = args.report_name
    if args.existing:
        report = {"test": "actual_asr_existing_media_no_online_parse", "results": [existing(t, args.engine) for t in args.existing]}
    elif args.gpu:
        report = {"test": "actual_gpu_inference_and_switch", "results": gpu()}
    else:
        samples = read_json(Path(args.samples), [])
        report = {"test": "actual_container_download_and_asr" if args.asr else "clean_anonymous_container_download", "results": []}
        for repeat in range(args.repeat):
            for sample in samples:
                result = run_sample(sample, repeat, args.asr)
                report["results"].append(result)
                atomic_json(Path("/verification") / f"{name}-progress.json", report)
                print({k: v for k, v in result.items() if k in {"label", "status", "error", "duration_s"}}, flush=True)
        report["coverage"] = {"samples": len(samples), "repeats": args.repeat,
                               "valid_short_link_present": any(s.get("expect") == "success" and "v.douyin.com" in s["input"] for s in samples),
                               "captcha_observed": any(s.get("error") == "verification_required" for s in report["results"])}
    path = Path("/verification") / f"{name}.json"
    atomic_json(path, report)
    for result in report["results"]:
        print({k: v for k, v in result.items() if k in {"label", "engine", "status", "error", "duration_s"}}, flush=True)
    return 0 if report["results"] and all(r["status"] == "passed" for r in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
