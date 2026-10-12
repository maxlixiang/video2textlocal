"""Explicit model provisioning; never runs as an import side effect."""
import os
import contextlib
import sys
import logging
from pathlib import Path

from .core import asr_config, atomic_json, file_hash, fingerprint, read_json


def quiet_download(fn, *args, **kwargs):
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        return fn(*args, **kwargs)


def prepare():
    root = Path(os.getenv("MODEL_ROOT", "/models")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = read_json(root / "models.lock.json", {})
    for engine in ("whisper", "funasr"):
        print(engine + " provisioning fixed model revision", flush=True)
        config = asr_config(engine)
        paths = {}
        if engine == "whisper":
            from huggingface_hub import snapshot_download
            paths["asr"] = Path(quiet_download(snapshot_download, repo_id=config["model"], revision=config["revision"],
                                                  cache_dir=str(root / "huggingface")))
        else:
            from modelscope.hub.snapshot_download import snapshot_download
            for label, name, revision in (("asr", "model", "revision"), ("vad", "vad_model", "vad_revision"),
                                          ("punc", "punc_model", "punc_revision")):
                paths[label] = Path(quiet_download(snapshot_download, config[name], revision=config[revision], cache_dir=str(root / "modelscope")))
        models = {}
        for label, path in paths.items():
            inventory = {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob("*")) if p.is_file()}
            models[label] = {"path": str(path.relative_to(root)), "content_hash": fingerprint(inventory)}
        lock[engine] = {"config": config, "models": models}
        atomic_json(root / "models.lock.json", lock)
        print(engine + " models downloaded and content-locked; GPU inference NOT yet verified", flush=True)


if __name__ == "__main__":
    try:
        logging.disable(logging.CRITICAL)
        # Remote SDK exceptions may contain signed URLs. Never emit their full text/traceback.
        prepare()
    except Exception as exc:
        print("model_provision_failed " + type(exc).__name__, flush=True)
        sys.exit(1)
