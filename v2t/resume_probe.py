"""Explicit offline media recovery test. Run in a network=none container."""
import argparse
import os
import shutil
import uuid
from pathlib import Path

from .core import atomic_json, media_dir, read_json, task_dir
from .download import download_task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("url")
    args = parser.parse_args()
    root = Path(os.getenv("DATA_ROOT", "/results"))
    existing = task_dir(root, args.task_id)
    original = read_json(media_dir(existing) / "media.json")
    # Complete cache must be reused with no network access.
    reused = download_task(existing, args.url)
    assert reused["sha256"] == original["sha256"]
    # Simulate a crash between committed media and metadata by creating one explicit fixture file.
    tid = uuid.uuid4().hex
    fixture = task_dir(root, tid)
    source = media_dir(fixture)
    source.mkdir(parents=True)
    shutil.copyfile(media_dir(existing) / "media.bin", source / "media.bin")
    restored = download_task(fixture, args.url)
    assert restored["sha256"] == original["sha256"]
    assert restored["audio_sha256"] == original["audio_sha256"]
    report = {"status": "passed", "network": "none", "complete_cache_reused": True,
              "metadata_commit_crash_recovered": True, "existing_task": args.task_id, "fixture_task": tid}
    atomic_json(Path("/verification/media-resume.json"), report)
    print(report)


if __name__ == "__main__":
    main()
