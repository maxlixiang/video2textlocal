from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ERRORS = {
    "network_error": "网络连接或传输失败。",
    "no_video": "下载内容没有视频画面。",
    "send_too_large": "媒体超过 Telegram 云端上传上限。",
    "send_forbidden": "机器人没有向该聊天发送的权限。",
    "send_rate_limited": "Telegram 暂时限制发送频率。",
    "adapter_disabled": "Windows 抖音适配器未启用。",
    "adapter_unavailable": "Windows 下载工作进程尚未连接。",
    "adapter_auth": "适配器认证失败或证书不可用。",
    "adapter_queue_expired": "Windows 下载排队期限已过。",
    "adapter_lease_expired": "下载租约或执行期限已过。",
    "adapter_memory_limit": "Windows 下载进程超过内存预算。",
    "adapter_quota": "媒体暂存总额度不足。",
    "disk_full": "剩余磁盘空间低于要求。",
    "adapter_offset": "上传偏移或分块校验不一致。",
    "invalid_input": "未找到受支持的视频链接。",
    "queue_full": "队列已满，请稍后再试。",
    "verification_required": "抖音要求验证码或登录，匿名下载已停止。",
    "unavailable": "作品失效、私密或匿名不可访问。",
    "target_mismatch": "页面返回的作品与目标 ID 不匹配，已停止下载。",
    "no_media": "没有找到视频或可解码音轨。",
    "download_failed": "下载失败；可重试，已有完整媒体会保留。",
    "douyin_empty_response": "抖音视频接口返回空内容，当前匿名出口未能取得媒体。",
    "douyin_script_failed": "抖音页面脚本加载失败，请检查容器出口网络。",
    "douyin_parse_timeout": "抖音匿名解析超时，未取得目标媒体；未自动登录或绕过验证。",
    "third_party_unavailable": "X 下载依赖的 fxtwitter 服务不可用或返回异常。",
    "too_large": "媒体超过大小上限。",
    "too_long": "媒体超过时长上限。",
    "timeout": "处理超时，未无限重试。",
    "gpu_unavailable": "GPU 或 CUDA 运行库不可用；未回退 CPU/云端。",
    "gpu_oom": "GPU 显存不足；未回退 CPU/云端。",
    "asr_failed": "本地识别失败。",
    "empty_transcript": "没有识别到语音内容。",
    "deepseek_missing": "未配置 DeepSeek 密钥；原稿仍然可用。",
    "deepseek_auth": "DeepSeek API 认证或权限失败，请检查密钥。",
    "deepseek_config": "DeepSeek 模型或请求配置无效，请检查配置。",
    "deepseek_rate_limited": "DeepSeek 请求被限流或额度不足，请稍后重试并检查账户。",
    "polish_failed": "整理失败；已保存的原稿和整理块会保留。",
    "polish_truncated": "整理响应被截断，未提交为完整整理稿。",
    "segment_over_budget": "单个识别片段超过整理预算，需要调大预算或细化识别分段。",
    "send_failed": "Telegram 发送失败；重试仅补未确认发送的附件。",
    "service_unavailable": "内部服务暂不可用。",
    "invalid_artifact": "结果文件校验失败。",
    "internal_error": "内部处理失败，请查看任务阶段与错误码。",
}


class Failure(Exception):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "internal_error"
        super().__init__(ERRORS[self.code])


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def task_dir(root: Path, task_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", task_id):
        raise Failure("invalid_input")
    return root / task_id


def media_dir(result_dir: Path) -> Path:
    return task_dir(Path(os.getenv("MEDIA_ROOT", "/media")), result_dir.name)


@dataclass(frozen=True)
class Target:
    platform: str
    url: str
    media_id: str


def parse_target(text: str) -> Target:
    for raw in re.findall(r"https?://[^\s<>]+", text):
        raw = raw.rstrip('。，；！、）)]\"\'')
        p = urlsplit(raw)
        host = (p.hostname or "").lower()
        if p.username or p.password or p.port not in (None, 80, 443):
            continue
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            vid = p.path.strip("/") if host == "youtu.be" else parse_qs(p.query).get("v", [""])[0]
            if not vid:
                m = re.fullmatch(r"/(?:shorts|live|embed)/([\w-]{11})/?", p.path)
                vid = m.group(1) if m else ""
            if re.fullmatch(r"[\w-]{11}", vid):
                return Target("youtube", f"https://www.youtube.com/watch?v={vid}", vid)
        if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
            m = re.search(r"/([A-Za-z0-9_]+)/status/(\d{5,25})", p.path)
            if m:
                return Target("x", f"https://x.com/{m[1]}/status/{m[2]}", m[2])
        if host in {"douyin.com", "www.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}:
            m = re.search(r"/(?:share/)?video/(\d{6,25})", p.path)
            vid = m[1] if m else parse_qs(p.query).get("modal_id", [""])[0]
            if re.fullmatch(r"\d{6,25}", vid):
                return Target("douyin", f"https://www.douyin.com/video/{vid}", vid)
        if host == "v.douyin.com" and re.fullmatch(r"/[A-Za-z0-9_-]{4,24}/?", p.path):
            return Target("douyin", f"https://v.douyin.com/{p.path.strip('/')}/", "")
    raise Failure("invalid_input")


def word_file(path):
    try:
        lines=Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        raise Failure("invalid_input") from None
    words=[]
    for line in lines:
        value=" ".join(line.split("#",1)[0].split()).strip()
        if value and value not in words:words.append(value)
    return words


def model_config(config):
    # Hotwords are runtime decoding hints, not a model artifact version.
    return {k:v for k,v in config.items() if k != "hotwords"}


def asr_config(engine: str) -> dict:
    if engine not in {"whisper", "funasr"}:
        raise Failure("invalid_input")
    if engine == "whisper":
        return {"engine": engine, "model": os.getenv("WHISPER_MODEL", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
                "revision": os.getenv("WHISPER_REVISION", "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"),
                "device": "cuda", "compute_type": "float16", "language": None,
                "beam_size": 5, "vad_filter": True, "implementation": "v1", "faster_whisper": "1.2.1", "ctranslate2": "4.6.0"}
    default_file = Path(__file__).resolve().parent.parent / "config" / "hotwords.txt"
    selected_file = os.getenv("HOTWORDS_FILE")
    words = word_file(selected_file) if selected_file else word_file(default_file) if default_file.exists() else []
    words += os.getenv("HOTWORDS", "涉外律师 涉外法律 出海 合规 尽职调查").split()
    return {"engine": engine, "model": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "revision": "v2.0.4", "vad_model": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "vad_revision": "v2.0.4",
            "punc_model": "iic/punc_ct-transformer_cn-en-common-vocab471067-large", "punc_revision": "v2.0.4",
            "device": "cuda", "compute_type": "float32", "language": "zh", "batch_size_s": 60,
            "hotwords": list(dict.fromkeys(words)), "implementation": "v1", "funasr": "1.2.7", "torch": "2.5.1+cu121"}


def validate_segments(segments):
    if not isinstance(segments, list) or not segments:
        raise Failure("empty_transcript")
    import math
    last_start = -1.0
    for s in segments:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
            raise Failure("invalid_artifact")
        start, end = float(s["start"]), float(s["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start or start < last_start:
            raise Failure("invalid_artifact")
        last_start = start


def timestamp(seconds):
    ms = round(float(seconds) * 1000)
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, frac = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{frac:03d}"


def write_transcript(path: Path, segments, metadata: dict, title="原稿", timestamps=True):
    validate_segments(segments)
    lines = [f"# {title}", "", f"- 引擎：{metadata.get('engine', 'DeepSeek')}",
             f"- 实际设备：{metadata.get('device', '文本 API')}", f"- 精度：{metadata.get('compute_type', '不适用')}", ""]
    for s in segments:
        if timestamps:
            lines.append(f"[{timestamp(s['start'])} - {timestamp(s['end'])}]")
        lines.extend([s["text"].strip(), ""])
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


class Store:
    """Only the manager process writes SQLite. All calls are on its event-loop thread."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY, dedupe TEXT UNIQUE, owner INTEGER, chat INTEGER,
                url TEXT, platform TEXT, media_id TEXT, engine TEXT, polish INTEGER DEFAULT 0,
                status TEXT DEFAULT 'choice', stage TEXT DEFAULT 'choice', error TEXT,
                raw_sent INTEGER DEFAULT 0, polished_sent INTEGER DEFAULT 0,
                status_message INTEGER, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, task_id TEXT, stage TEXT, status TEXT, error TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS deliveries(task_id TEXT, kind TEXT, content_hash TEXT, message_id INTEGER,
                PRIMARY KEY(task_id,kind,content_hash));
        """)

        columns = {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}
        if "queued_at" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN queued_at REAL")
            self.db.commit()

        if "mode" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN mode TEXT DEFAULT 'transcript'")
            self.db.commit()

    def get(self, tid):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None

    def create(self, dedupe, owner, chat, target: Target):
        tid = uuid.uuid4().hex
        now = time.time()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO tasks(id,dedupe,owner,chat,url,platform,media_id,engine,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (tid, dedupe, owner, chat, target.url, target.platform, target.media_id,
                 "funasr" if target.platform == "douyin" else "whisper", now, now))
        return dict(self.db.execute("SELECT * FROM tasks WHERE dedupe=?", (dedupe,)).fetchone())

    def update(self, tid, **values):
        allowed = {"status", "stage", "error", "raw_sent", "polished_sent", "status_message", "engine", "polish", "queued_at", "mode"}
        if not values or not values.keys() <= allowed:
            raise ValueError("invalid fields")
        values["updated"] = time.time()
        with self.db:
            self.db.execute("UPDATE tasks SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*values.values(), tid))

    def event(self, tid, stage, status, error=None):
        with self.db:
            self.db.execute("INSERT INTO events(task_id,stage,status,error,created) VALUES(?,?,?,?,?)",
                            (tid, stage, status, error, time.time()))

    def delivered(self, tid, kind, content_hash):
        return self.db.execute("SELECT 1 FROM deliveries WHERE task_id=? AND kind=? AND content_hash=?",
                               (tid, kind, content_hash)).fetchone() is not None

    def delivery(self, tid, kind, content_hash, message_id):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?)", (tid, kind, content_hash, message_id))

    def enqueue(self, tid, owner, polish, limit=20, mode=None):
        with self.db:
            row = self.get(tid)
            if not row or row["owner"] != owner or row["status"] not in {"choice", "failed"}:
                return False
            count = self.db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]
            if count >= limit:
                raise Failure("queue_full")
            selected_mode = mode or row["mode"]
            if selected_mode not in {"transcript", "video"}: raise ValueError("invalid mode")
            self.update(tid, status="queued", stage="queued", error=None, polish=int(polish) if selected_mode != "video" else 0, mode=selected_mode, queued_at=time.time())
        return True

    def claim(self):
        with self.db:
            row = self.db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                self.update(row["id"], status="running")
                return self.get(row["id"])
        return None

    def recover(self):
        with self.db:
            self.db.execute("UPDATE tasks SET status='queued' WHERE status='running'")

    def get_offset(self):
        r = self.db.execute("SELECT value FROM kv WHERE key='offset'").fetchone()
        return int(r[0]) if r else 0

    def offset(self, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES('offset',?)", (str(value),))
