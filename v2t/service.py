"""Internal-only services. One GPU child at a time; process exit releases both runtimes."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import Failure, read_json, task_dir

ROOT = Path(os.getenv("DATA_ROOT", "/data/tasks"))
ROLE = os.getenv("SERVICE_ROLE", "download")
CAPACITY = threading.BoundedSemaphore(1 if ROLE == "gpu" else int(os.getenv("DOWNLOAD_CONCURRENCY", "2")))
DOUYIN = threading.BoundedSemaphore(1)


def run_child(role, directory, payload):
    import uuid
    request = directory / ("request-" + uuid.uuid4().hex + ".json")
    result = request.with_suffix(".result.json")
    from .core import atomic_json
    atomic_json(request, payload)
    timeout = int(os.getenv("ASR_TIMEOUT", "7200") if role == "gpu" else os.getenv("DOWNLOAD_TIMEOUT", "600"))
    proc = subprocess.Popen([sys.executable, "-m", "v2t.worker", role, str(directory), str(request), str(result)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    memory_samples = []
    def sample_memory():
        try:
            output = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                             stderr=subprocess.DEVNULL, timeout=3).decode().splitlines()
            return int(output[0].strip())
        except Exception:
            return None
    baseline = sample_memory() if role == "gpu" else None
    started = time.monotonic()
    try:
        if role == "gpu":
            while proc.poll() is None:
                value = sample_memory()
                if value is not None:
                    memory_samples.append(value)
                if time.monotonic() - started > timeout:
                    raise subprocess.TimeoutExpired(proc.args, timeout)
                time.sleep(0.5)
        else:
            proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise Failure("timeout") from None
    data = read_json(result)
    if not data:
        raise Failure("asr_failed" if role == "gpu" else "download_failed")
    if data.get("error"):
        raise Failure(data["error"])
    if proc.returncode:
        raise Failure("internal_error")
    if role == "gpu":
        data["actual"]["gpu_memory_baseline_mib"] = baseline
        data["actual"]["gpu_memory_used_peak_mib"] = max(memory_samples) if memory_samples else None
        data["actual"]["gpu_memory_after_child_exit_mib"] = sample_memory()
        data["actual"]["gpu_memory_measurement"] = "whole_device_nvidia_smi_includes_other_processes"
        atomic_json(directory / "raw.json", data)
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, data, status=200):
        encoded = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/configuration" and ROLE == "gpu":
            try:
                from .core import asr_config
                return self.reply({"configs":{e:asr_config(e) for e in ("funasr","whisper")}})
            except Failure as e:return self.reply({"error":e.code})
        if self.path == "/health":
            from .readiness import check
            result = check(ROLE)
            return self.reply(result, 200 if result["ready"] else 503)
        self.reply({"error": "invalid_input"}, 404)

    def do_POST(self):
        if self.path == "/maintenance/media" and ROLE == "download":
            from .adapter_common import key
            import hmac
            try:
                if not hmac.compare_digest(self.headers.get("X-Adapter-Key", ""), key()):raise Failure("adapter_auth")
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=1024:raise Failure("invalid_input")
                payload=json.loads(self.rfile.read(size))
                from .retention import remove_one,seconds
                ttl=seconds()
                if not ttl:raise Failure("invalid_input")
                return self.reply(remove_one(Path(os.getenv("MEDIA_ROOT","/media")),payload["task_id"],time.time()-ttl))
            except Failure as e:return self.reply({"error":e.code})
            except Exception:return self.reply({"error":"internal_error"})
        if self.path == "/adapter/cache":
            from .adapter_common import enabled, key
            import hmac
            try:
                if not enabled() or not hmac.compare_digest(self.headers.get("X-Adapter-Key", ""), key()):
                    raise Failure("adapter_auth")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384: raise Failure("invalid_input")
                payload = json.loads(self.rfile.read(size))
                from .download import cached_media
                from .core import media_dir, parse_target
                target = parse_target(payload["url"])
                source_dir = media_dir(task_dir(ROOT, payload["task_id"]))
                if (source_dir / "media.bin").exists() and not (source_dir / "media.json").exists():
                    from .core import file_hash
                    receipts = [read_json(p, {}) for p in source_dir.glob("adapter/*/receipt.json")]
                    verified = any(r.get("sha256") == file_hash(source_dir / "media.bin") and r.get("resolved_id") == r.get("matched_id")
                        and (not target.media_id or target.media_id == r.get("matched_id")) for r in receipts)
                    if not verified: raise Failure("invalid_artifact")
                found = cached_media(source_dir, target, bool(payload.get("want_video")))
                return self.reply({"cached": bool(found)})
            except Failure as e: return self.reply({"error": e.code})
            except Exception: return self.reply({"error": "invalid_artifact"})
        if self.path != "/run":
            return self.reply({"error": "invalid_input"}, 404)
        try:
            from .readiness import check
            readiness = check(ROLE)
            if not readiness["ready"]:
                raise Failure(readiness.get("error", "service_unavailable"))
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise Failure("invalid_input")
            payload = json.loads(self.rfile.read(size))
            directory = task_dir(ROOT, payload["task_id"])
            directory.mkdir(parents=True, exist_ok=True)
            from .core import parse_target
            is_douyin = ROLE == "download" and parse_target(payload["url"]).platform == "douyin"
            if ROLE == "gpu":
                from .core import asr_config
                cfg=asr_config(payload["engine"])
                if payload.get("config") != cfg:raise Failure("asr_config_mismatch")
                from .core import model_config
                lock=read_json(Path(os.getenv("MODEL_ROOT","/models"))/"models.lock.json",{}).get(payload["engine"],{})
                if model_config(lock.get("config",{})) != model_config(cfg):raise Failure("asr_config_mismatch")
            with CAPACITY:
                if is_douyin:
                    with DOUYIN:
                        result = run_child(ROLE, directory, payload)
                else:
                    result = run_child(ROLE, directory, payload)
            self.reply(result)
        except Failure as exc:
            self.reply({"error": exc.code})
        except Exception:
            self.reply({"error": "internal_error"})


def main():
    if ROLE not in {"gpu", "download"}:
        raise SystemExit("invalid service role")
    from .adapter_common import enabled
    if ROLE == "download" and enabled():
        from .adapter_gateway import start_gateway
        start_gateway()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
