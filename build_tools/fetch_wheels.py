"""Download fixed new GPU dependencies concurrently and verify against official PyPI SHA-256.

No package installation or system settings changed. Cached files are never bulk-deleted.
"""
import concurrent.futures
import hashlib
import html
import json
import re
import time
import urllib.request
from urllib.parse import urljoin
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheelhouse"


def score(filename):
    if not filename.endswith(".whl"):
        return 1 if filename.endswith(".tar.gz") else -1
    if any(t in filename for t in ("aarch64", "arm64", "musllinux", "win_", "macosx", "i686")):
        return -1
    if "none-any.whl" in filename:
        return 100
    if "x86_64" not in filename:
        return -1
    glibc = re.findall(r"manylinux_2_(\d+)", filename)
    if glibc and min(map(int, glibc)) > 35:
        return -1
    if "cp311-cp311" in filename:
        return 300
    if "py3-none-" in filename or "py2.py3-none-" in filename:
        return 250
    abi = re.search(r"cp(\d+)-abi3", filename)
    if abi and int(abi[1]) <= 311:
        return 200 + int(abi[1]) / 1000
    return -1


def fetch(spec):
    name, version = spec.split("==")
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as r:
        meta = json.load(r)
    files = sorted(meta["urls"], key=lambda x: score(x["filename"]), reverse=True)
    entry = files[0]
    if score(entry["filename"]) < 0:
        raise RuntimeError("no compatible file: " + spec)
    dest = WHEELS / entry["filename"]
    wanted = entry["digests"]["sha256"]
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == wanted:
        return {"name": name, "version": version, "file": dest.name, "sha256": wanted}
    # Use a measured faster mirror, but authenticate file bytes using official PyPI metadata.
    index_url = "https://mirrors.aliyun.com/pypi/simple/" + name.lower().replace("_", "-") + "/"
    with urllib.request.urlopen(index_url, timeout=30) as r:
        index = r.read().decode()
    links = [urljoin(index_url, html.unescape(u).split("#")[0]) for u in re.findall(r'href="([^"]+)"', index)]
    url = next((u for u in links if u.split("?")[0].endswith("/" + entry["filename"])), entry["url"])
    started = time.monotonic()
    temp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=30) as r, temp.open("wb") as f:
        while True:
            if time.monotonic() - started > 240:
                raise TimeoutError(spec)
            block = r.read(256 * 1024)
            if not block:
                break
            h.update(block)
            f.write(block)
    if h.hexdigest() != wanted:
        raise RuntimeError("hash mismatch: " + spec)
    temp.replace(dest)
    print("verified", spec, flush=True)
    return {"name": name, "version": version, "file": dest.name, "sha256": wanted}


def main():
    WHEELS.mkdir(exist_ok=True)
    specs = [s.strip() for s in (ROOT / "requirements-gpu.lock").read_text().splitlines() if s.strip() and not s.startswith("#")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(fetch, specs))
    (WHEELS / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("all fixed wheels verified", len(records))


if __name__ == "__main__":
    main()
