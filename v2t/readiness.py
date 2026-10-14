"""Readiness checks contain only fixed error codes and public expiry metadata."""
import json
import os
import shutil
import ssl
import subprocess
import time
from pathlib import Path
from .core import Failure, asr_config, model_config, read_json


def check(role):
    try:
        for name, default, minimum in (("DATA_ROOT", "/results", "RESULT_MIN_FREE_BYTES"),
                                        ("MEDIA_ROOT", "/media", "MEDIA_MIN_FREE_BYTES")):
            root = Path(os.getenv(name, default))
            if not root.is_dir():
                raise Failure("invalid_artifact")
            if shutil.disk_usage(root).free < int(os.getenv(minimum, "536870912")):
                raise Failure("disk_full")
        if role == "gpu":
            locks = read_json(Path(os.getenv("MODEL_ROOT", "/models")) / "models.lock.json", {})
            for engine in ("funasr", "whisper"):
                if model_config(locks.get(engine, {}).get("config", {})) != model_config(asr_config(engine)):
                    raise Failure("asr_config_mismatch")
            subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        if role == "download" and os.getenv("WINDOWS_ADAPTER_ENABLED") == "1":
            from .adapter_common import key, cert_remaining
            if not key() or not read_json(Path(os.environ["ADAPTER_WORKERS_FILE"]), {}):
                raise Failure("adapter_auth")
            cert = Path(os.environ["ADAPTER_SERVER_CERT"])
            directory = cert.parent.resolve()
            if cert_remaining(directory / cert.name) < 900:
                raise Failure("adapter_certificate")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(directory / cert.name, directory / Path(os.environ["ADAPTER_SERVER_KEY"]).name)
            context.load_verify_locations(os.environ["ADAPTER_CA_FILE"])
            expiry = read_json(directory / "expiry.json", {})
            if float(expiry.get("ca_expires", 0)) < time.time() + 900:
                raise Failure("adapter_certificate")
            warnings = []
            if expiry["ca_expires"] < time.time() + 30 * 86400: warnings.append("ca_renew_within_30_days")
            if cert_remaining(directory / cert.name) < 14 * 86400: warnings.append("leaf_renew_within_14_days")
            return {"ready": True, "role": role, "warnings": warnings}
        return {"ready": True, "role": role}
    except Failure as exc:
        return {"ready": False, "role": role, "error": exc.code}
    except Exception:
        return {"ready": False, "role": role, "error": "startup_prerequisite_missing"}


def manager_health():
    value = read_json(Path(os.getenv("DB_ROOT", "/database")) / "readiness.json", {})
    return bool(value.get("ready") and time.time() - value.get("checked_at", 0) < 35)


if __name__ == "__main__":
    raise SystemExit(0 if manager_health() else 1)
