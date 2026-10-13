from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .core import Failure, atomic_json, file_hash, media_dir, parse_target, read_json
from .net import open_public

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
MAX_BYTES = int(os.getenv("MAX_MEDIA_BYTES", "524288000"))
MAX_SECONDS = int(os.getenv("MAX_MEDIA_SECONDS", "7200"))
TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "600"))


def probe_info(path: Path):
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=30, check=True)
        info = json.loads(p.stdout)
        video = any(x.get("codec_type") == "video" for x in info.get("streams", []))
        formats = info.get("format", {}).get("format_name", "").split(",")
        return {"has_audio": any(x.get("codec_type") == "audio" for x in info.get("streams", [])), "has_video": video, "extension": "mp4" if "mp4" in formats else "webm" if "webm" in formats else "mkv"}
    except Exception:
        raise Failure("no_media") from None


def probe(path: Path, require_audio=True):
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                           capture_output=True, timeout=30, check=True)
        info = json.loads(p.stdout)
        duration = float(info["format"]["duration"])
        if (require_audio and not any(s.get("codec_type") == "audio" for s in info["streams"])) or duration <= 0:
            raise Failure("no_media")
        if duration > MAX_SECONDS:
            raise Failure("too_long")
        if path.stat().st_size > MAX_BYTES:
            raise Failure("too_large")
        return duration
    except Failure:
        raise
    except Exception:
        raise Failure("no_media") from None


def decode_audio(media: Path, audio: Path):
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-y", "-i", str(media),
                        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=True)
        if audio.stat().st_size < 100:
            raise Failure("no_media")
    except subprocess.TimeoutExpired:
        raise Failure("timeout") from None
    except Failure:
        raise
    except Exception:
        raise Failure("no_media") from None


def decode_video(media):
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(media), "-map", "0:v:0", "-f", "null", "-"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=True)
    except subprocess.TimeoutExpired: raise Failure("timeout") from None
    except Exception: raise Failure("no_media") from None


def cached_media(directory: Path, target=None, want_video=False):
    meta = read_json(directory / "media.json")
    media, audio = directory / "media.bin", directory / "audio.wav"
    # Recover a crash after final media rename but before metadata commit, without online parsing.
    if media.exists() and meta is None:
        properties = probe_info(media)
        duration = probe(media, require_audio=not want_video)
        temporary = directory / "audio.part.wav"
        if properties["has_audio"]:
            decode_audio(media, temporary)
            temporary.replace(audio)
        else:
            decode_video(media)
        meta = {**properties, "sha256": file_hash(media), "audio_sha256": file_hash(audio) if properties["has_audio"] else None, "bytes": media.stat().st_size,
                "duration": duration, "media_id": target.media_id if target else "", "platform": target.platform if target else "recovered",
                "validation": "recovered_ffprobe+full_ffmpeg_decode"}
        atomic_json(directory / "media.json", meta)
    if not meta or not media.exists() or meta.get("sha256") != file_hash(media):
        return None
    if "has_video" not in meta:
        meta.update(probe_info(media))
        atomic_json(directory / "media.json", meta)
    if target and target.platform=="x" and meta.get("video_index",1)!=target.video_index:return None
    if want_video and not meta["has_video"]:
        return None
    # Check full-media limits and decode again when audio is absent/corrupt.
    probe(media, require_audio=not want_video)
    if want_video and not meta.get("has_audio", True): return meta
    if not audio.exists() or meta.get("audio_sha256") != file_hash(audio):
        temp = directory / "audio.part.wav"
        decode_audio(media, temp)
        temp.replace(audio)
        meta["audio_sha256"] = file_hash(audio)
        atomic_json(directory / "media.json", meta)
    return meta


def stream_file(url, dest: Path, headers=None, opener=None):
    started = time.monotonic()
    size = 0
    if opener:
        from urllib.request import Request
        from .net import public_url
        try:
            response = opener.open(Request(public_url(url), headers=headers or {}),timeout=45)
        except Failure:
            raise
        except Exception:
            raise Failure("download_failed") from None
    else:
        response = open_public(url, timeout=45, headers=headers)
    with response as r:
        try:
            declared = int(r.headers.get("Content-Length", "0"))
        except ValueError:
            declared = 0
        if declared > MAX_BYTES:
            raise Failure("too_large")
        with dest.open("wb") as f:
            while True:
                if time.monotonic() - started > TIMEOUT:
                    raise Failure("timeout")
                block = r.read(1024 * 256)
                if not block:
                    break
                size += len(block)
                if size > MAX_BYTES:
                    raise Failure("too_large")
                from .storage import protect
                protect(Path(os.getenv("MEDIA_ROOT","/media")),len(block),"media")
                f.write(block)
    if size < 2048:
        raise Failure("no_media")
    if declared and not r.headers.get("Content-Encoding") and size != declared:
        raise Failure("download_failed")


def youtube(target, directory, want_video=False):
    import yt_dlp

    class Quiet:
        def debug(self, *args): pass
        def warning(self, *args): pass
        def error(self, *args): pass

    def limit(info, *, incomplete=False):
        duration = info.get("duration")
        if duration and duration > MAX_SECONDS:
            return "duration_limit"
        if info.get("is_live"):
            return "live_not_supported"
        return None

    def progress(info):
        from .storage import protect
        protect(Path(os.getenv("MEDIA_ROOT", "/media")), 0, "media")
        if info.get("downloaded_bytes", 0) > MAX_BYTES:
            raise Failure("too_large")

    prefix = "yt-" + uuid.uuid4().hex
    options = {"format": "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]" if want_video else "bestaudio/best", "noplaylist": True, "outtmpl": str(directory / (prefix + ".%(ext)s")),
               "socket_timeout": 30, "retries": 1, "fragment_retries": 1, "max_filesize": MAX_BYTES,
               "match_filter": limit, "progress_hooks": [progress], "logger": Quiet(), "quiet": True,
               "concurrent_fragment_downloads": 1, "cachedir": False, "js_runtimes": {"deno": {}}}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(target.url, download=False)
            if not info or info.get("id") != target.media_id:
                raise Failure("target_mismatch")
            if info.get("is_live"):
                raise Failure("unavailable")
            if (info.get("duration") or 0) > MAX_SECONDS:
                raise Failure("too_long")
            ydl.download([target.url])
        files = [p for p in directory.glob(prefix + ".*") if p.is_file() and p.suffix not in {".part", ".ytdl", ".json"}]
        if len(files) != 1:
            raise Failure("download_failed")
        return files[0], target.media_id, str(info.get("title") or "")[:500]
    except Failure:
        raise
    except Exception:
        raise Failure("download_failed") from None




def build_fxtwitter_mp4_url(tweet_id):
    # Reused verbatim endpoint from old twitter_downloader.py::build_fxtwitter_mp4_url.
    return f"https://fxtwitter.com/i/status/{tweet_id}.mp4"


def indexed_twitter_video(item, index):
    # X /video/N uses the position in the mixed photo/video attachment list.
    media = item.get("media", {})
    attachments = media.get("all")
    if not isinstance(attachments, list):
        # Without mixed-order evidence we cannot safely infer an index around photos.
        if media.get("photos"): raise Failure("no_media")
        attachments = media.get("videos", [])
    if not 1 <= index <= len(attachments): raise Failure("no_media")
    chosen = attachments[index - 1]
    if chosen.get("type", "video") != "video" or not chosen.get("url"): raise Failure("no_video")
    return chosen["url"]


def twitter(target, directory):
    path = directory / ("x-" + uuid.uuid4().hex + ".part")
    try:
        selected_url = build_fxtwitter_mp4_url(target.media_id)
        if target.video_index > 1:
            with open_public(f"https://api.fxtwitter.com/status/{target.media_id}", timeout=15) as response:
                info=json.loads(response.read(1024*1024))
            item=info.get("tweet") or info.get("status") or {}
            if str(item.get("id")) != target.media_id: raise Failure("target_mismatch")
            selected_url=indexed_twitter_video(item, target.video_index)
        stream_file(selected_url, path, {"User-Agent": UA})
        with path.open("rb") as f:
            header = f.read(16)
        if len(header) < 8 or header[4:8] != b"ftyp":
            raise Failure("third_party_unavailable")
        probe(path, require_audio=False)
    except Failure as exc:
        if exc.code in {"too_large", "too_long", "timeout"}:
            raise
        raise Failure("third_party_unavailable") from None
    title = ""
    try:
        with open_public(f"https://api.fxtwitter.com/status/{target.media_id}", timeout=10) as response:
            info = json.loads(response.read(1024 * 1024))
        item = info.get("tweet") or info.get("status") or {}
        if str(item.get("id")) == target.media_id: title = str(item.get("text") or "")[:500]
    except Exception:
        pass  # Optional title failure cannot discard an already verified MP4.
    return path, target.media_id, title




def douyin(target, directory):
    from .douyin_parser import fetch_meta
    meta = fetch_meta(target.url, directory)
    if target.media_id and target.media_id != meta["aweme_id"]:
        raise Failure("target_mismatch")
    last = Failure("download_failed")
    for url in meta["video_urls"][:6]:
        if not url.startswith(("https://", "http://")):
            continue
        dest = directory / ("dy-" + uuid.uuid4().hex + ".part")
        try:
            headers = dict(meta["headers"])
            from http.cookiejar import Cookie, CookieJar
            from urllib.request import HTTPCookieProcessor, build_opener, Request
            from .net import SafeRedirect, public_url
            jar = CookieJar()
            for c in meta["cookies"]:
                jar.set_cookie(Cookie(0,c["name"],c["value"],None,False,c["domain"],c["domain"].startswith("."),
                                      c["domain"].startswith("."),c["path"],True,c.get("secure",False),
                                      int(c["expires"]) if c.get("expires",-1)>0 else None,False,None,None,{}))
            # URL-scoped anonymous CookieJar preserves domain/path on every redirect.
            opener = build_opener(SafeRedirect(), HTTPCookieProcessor(jar))
            stream_file(url, dest, headers, opener=opener)
            with dest.open("rb") as f:
                header = f.read(16)
            if len(header)<8 or header[4:8]!=b"ftyp":
                raise Failure("no_media")
            probe(dest)
            return dest, meta["aweme_id"], str(meta.get("title") or "")[:500]
        except Failure as exc:
            last = exc
            if exc.code in {"too_large","too_long","timeout"}:
                raise
    raise last


def download_task(directory: Path, url: str, want_video=False):
    directory = media_dir(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = parse_target(url)
    cached = cached_media(directory, target, want_video)
    if cached:
        return cached
    from .storage import protect
    protect(Path(os.getenv("MEDIA_ROOT","/media")),MAX_BYTES+MAX_SECONDS*32000,"media")
    if target.platform == "youtube":
        staged, media_id, title = youtube(target, directory, want_video)
    else:
        staged, media_id, title = {"x": twitter, "douyin": douyin}[target.platform](target, directory)
    properties = probe_info(staged)
    if want_video and not properties["has_video"]: raise Failure("no_video")
    duration = probe(staged, require_audio=not want_video)
    wav = directory / "audio.part.wav"
    if properties["has_audio"]:
        decode_audio(staged, wav)
    else:
        decode_video(staged)
    media, audio = directory / "media.bin", directory / "audio.wav"
    staged.replace(media)
    if properties["has_audio"]: wav.replace(audio)
    meta = {"sha256": file_hash(media), "audio_sha256": file_hash(audio) if properties["has_audio"] else None, "bytes": media.stat().st_size,
            "duration": duration, "media_id": media_id, "platform": target.platform, "video_index":target.video_index, "title": title, **properties, "validation": "ffprobe+full_ffmpeg_decode"}
    atomic_json(directory / "media.json", meta)
    return meta
