from __future__ import annotations

import asyncio
import fcntl
import os
from pathlib import Path

from .core import (ERRORS, Failure, Store, asr_config, file_hash, fingerprint, media_dir, parse_target,
                   read_json, task_dir, validate_segments, write_transcript, model_config)
from .net import json_request
from .polish import polish, cached_polished
from .telegram import Telegram
from .presentation import filename, short_title, error_text

LABELS = {"queued": "排队", "download": "下载", "recognize": "识别", "polish": "整理",
          "sending_video": "发送视频", "sending_raw": "发送原稿", "sending_polished": "发送整理稿", "done": "完成", "failed": "失败"}


def authorized(row, owner, allowed):
    return owner in allowed and bool(row) and row["owner"] == owner


def cached_raw(directory, engine, model_root):
    raw = read_json(directory / "raw.json")
    source_dir = media_dir(directory)
    media = read_json(source_dir / "media.json")
    lock = read_json(model_root / "models.lock.json", {}).get(engine)
    if not raw or not media or not lock or raw.get("config") != asr_config(engine) or model_config(lock.get("config", {})) != model_config(asr_config(engine)):
        return None
    for model in lock.get("models", {}).values():
        path = (model_root / model["path"]).resolve()
        if not path.is_relative_to(model_root.resolve()) or not path.is_dir():
            return None
        inventory = {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob("*")) if p.is_file()}
        if fingerprint(inventory) != model["content_hash"]:
            return None
    for name, key in (("media.bin", "sha256"), ("audio.wav", "audio_sha256")):
        path = source_dir / name
        if not path.exists() or file_hash(path) != media.get(key):
            return None
    expected = fingerprint({"media": media["sha256"], "audio": media["audio_sha256"],
                            "config": asr_config(engine), "weights": fingerprint(lock)})
    if raw.get("cache_key") != expected or raw.get("actual", {}).get("device") != "cuda":
        return None
    try:
        validate_segments(raw["segments"])
    except (Failure, KeyError, TypeError, ValueError):
        return None
    return raw


class Manager:
    def __init__(self, store, root, model_root, telegram, allowed, service=json_request, polisher=polish):
        self.store, self.root, self.model_root = store, root, model_root
        self.telegram, self.allowed = telegram, allowed
        self.service, self.polisher = service, polisher
        self.adapter = None

    def choices(self, row):
        tid = row["id"]
        return {"inline_keyboard": [[{"text": "视频下载", "callback_data": f"video:{tid}"}], [{"text": "发送原稿", "callback_data": f"raw:{tid}"},
                                     {"text": "发送 DeepSeek 整理稿＋原稿", "callback_data": f"both:{tid}"}],
                                    [{"text": f"引擎：{row['engine']}（点击切换）", "callback_data": f"engine:{tid}"}]]}

    async def answer_callback(self, callback_id, text, alert=False):
        try:
            await asyncio.to_thread(self.telegram.call, "answerCallbackQuery", {
                "callback_query_id": callback_id, "text": text, "show_alert": alert})
        except Failure:
            # Expired callback acknowledgements must not replay a committed queue action or stall polling.
            pass

    async def notify(self, tid, stage, error=None):
        self.store.update(tid, stage=stage, error=error)
        row = self.store.get(tid)
        source = read_json(media_dir(task_dir(self.root, tid)) / "media.json", {})
        name = short_title(source.get("title"), f"{row['platform']}_{row['media_id'] or tid[:8]}")
        text = f"{name}\n{LABELS.get(stage, stage)}"
        if row["mode"] != "video": text += f" · 本地识别 {row['engine']}"
        if error:
            text += "\n" + error_text(error, ERRORS)
        values = {"chat_id": row["chat"], "text": text}
        if stage == "failed":
            values["reply_markup"] = {"inline_keyboard": [[{"text": "重试未完成阶段", "callback_data": f"retry:{tid}"}]]}
        try:
            if row["status_message"]:
                values["message_id"] = row["status_message"]
                await asyncio.to_thread(self.telegram.call, "editMessageText", values)
            else:
                message = await asyncio.to_thread(self.telegram.call, "sendMessage", values)
                self.store.update(tid, status_message=message["message_id"])
        except Failure:
            # Status notification failure cannot invalidate media or ASR output.
            pass

    async def download(self, row):
        tid = row["id"]
        if row["platform"] == "douyin" and self.adapter is not None:
            from .adapter_common import key
            def cache_check():
                import json, urllib.request
                request = urllib.request.Request(os.getenv("DOWNLOAD_URL", "http://download:8080") + "/adapter/cache",
                    json.dumps({"task_id": tid, "url": row["url"], "want_video": row["mode"] == "video"}).encode(), headers={"X-Adapter-Key": key()})
                with urllib.request.urlopen(request, timeout=int(os.getenv("DOWNLOAD_TIMEOUT", "600"))) as response:
                    value = json.load(response)
                if value.get("error"): raise Failure(value["error"])
                return value["cached"]
            if not await asyncio.to_thread(cache_check):
                self.adapter.submit(row)
                # Yields to all control/heartbeat/SQLite operations while download executes elsewhere.
                await self.adapter.wait(tid)
        else:
            if row["platform"] == "douyin" and os.getenv("DOUYIN_LINUX_DIAGNOSTIC") != "1":
                raise Failure("adapter_disabled")
            await asyncio.to_thread(self.service, os.getenv("DOWNLOAD_URL", "http://download:8080") + "/run",
                                    {"task_id": tid, "url": row["url"], "want_video": row["mode"] == "video"}, timeout=int(os.getenv("DOWNLOAD_TIMEOUT", "600")) + 60)

    async def process(self, row):
        tid = row["id"]
        directory = task_dir(self.root, tid)
        try:
            from .storage import protect
            protect(self.root, kind="results")
            directory.mkdir(parents=True, exist_ok=True)
            if row["mode"] == "video":
                await self.process_video(row)
                return
            raw = await asyncio.to_thread(cached_raw, directory, row["engine"], self.model_root)
            if raw is None:
                self.store.update(tid, raw_sent=0, polished_sent=0)
                await self.notify(tid, "download")
                self.store.event(tid, "download", "running")
                await self.download(row)
                self.store.event(tid, "download", "success")
                await self.notify(tid, "recognize")
                self.store.event(tid, "recognize", "running")
                await asyncio.to_thread(self.service, os.getenv("GPU_URL", "http://gpu:8080") + "/run",
                                        {"task_id": tid, "engine": row["engine"], "config":asr_config(row["engine"])}, timeout=int(os.getenv("ASR_TIMEOUT", "7200")) + 60)
                raw = await asyncio.to_thread(cached_raw, directory, row["engine"], self.model_root)
                if raw is None:
                    raise Failure("invalid_artifact")
                self.store.event(tid, "recognize", "success")
            source = read_json(media_dir(directory) / "media.json", {})
            fallback = f"{row['platform']}_{source.get('media_id') or row['media_id'] or tid[:8]}"
            original = directory / filename(source.get("title"), "原稿", fallback=fallback)
            write_transcript(original, raw["segments"], raw["actual"])
            original_hash = file_hash(original)
            if not self.store.delivered(tid, "raw", original_hash):
                await self.notify(tid, "sending_raw")
                self.store.event(tid, "sending_raw", "running")
                message_id = await asyncio.to_thread(self.telegram.send_document, row["chat"], original, f"{short_title(source.get('title'), fallback)} · 原稿（本地识别，未经 DeepSeek 整理）")
                self.store.delivery(tid, "raw", original_hash, message_id)
                self.store.update(tid, raw_sent=1)
                self.store.event(tid, "sending_raw", "success")
            if row["polish"]:
                result = await asyncio.to_thread(cached_polished, directory, raw)
                if result is None:
                    await self.notify(tid, "polish")
                    self.store.event(tid, "polish", "running")
                    result = await asyncio.to_thread(self.polisher, directory, raw)
                    self.store.event(tid, "polish", "success")
                cleaned = directory / filename(source.get("title"), "deepseek转写", fallback=fallback)
                write_transcript(cleaned, result["segments"], {"engine": "DeepSeek"}, "整理稿", timestamps=False)
                cleaned_hash = file_hash(cleaned)
                if not self.store.delivered(tid, "polished", cleaned_hash):
                    await self.notify(tid, "sending_polished")
                    self.store.event(tid, "sending_polished", "running")
                    message_id = await asyncio.to_thread(self.telegram.send_document, row["chat"], cleaned, f"{short_title(source.get('title'), fallback)} · DeepSeek 忠实整理稿")
                    self.store.delivery(tid, "polished", cleaned_hash, message_id)
                    self.store.update(tid, polished_sent=1)
                    self.store.event(tid, "sending_polished", "success")
            self.store.update(tid, status="done")
            await self.notify(tid, "done")
        except Failure as exc:
            self.store.event(tid, self.store.get(tid)["stage"], "failed", exc.code)
            self.store.update(tid, status="failed")
            await self.notify(tid, "failed", exc.code)
        except Exception:
            self.store.event(tid, self.store.get(tid)["stage"], "failed", "internal_error")
            self.store.update(tid, status="failed")
            await self.notify(tid, "failed", "internal_error")

    async def process_video(self, row):
        tid = row["id"]
        await self.notify(tid, "download")
        self.store.event(tid, "download", "running")
        source = media_dir(task_dir(self.root, tid))
        meta = read_json(source / "media.json", {})
        media = source / "media.bin"
        cached = meta.get("has_video") and media.exists() and await asyncio.to_thread(file_hash, media) == meta.get("sha256")
        if not cached:
            await self.download(row)
            meta = read_json(source / "media.json", {})
        if not media.exists() or await asyncio.to_thread(file_hash, media) != meta.get("sha256"):
            raise Failure("invalid_artifact")
        if not meta.get("has_video"):
            raise Failure("no_video")
        self.store.event(tid, "download", "success")
        if not self.store.delivered(tid, "video", meta["sha256"]):
            await self.notify(tid, "sending_video")
            self.store.event(tid, "sending_video", "running")
            fallback = f"{row['platform']}_{meta.get('media_id') or tid[:8]}"
            name = filename(meta.get("title"), "视频", meta.get("extension", "mp4"), fallback)
            message_id = await asyncio.to_thread(self.telegram.send_media, row["chat"], media, name,
                f"{short_title(meta.get('title'), fallback)} · 视频（未转写）", meta.get("extension") == "mp4")
            self.store.delivery(tid, "video", meta["sha256"], message_id)
            self.store.event(tid, "sending_video", "success")
        self.store.update(tid, status="done")
        await self.notify(tid, "done")

    async def handle(self, update):
        callback = update.get("callback_query")
        if callback:
            owner = callback["from"]["id"]
            parts = callback.get("data", "").split(":", 1)
            row = self.store.get(parts[1]) if len(parts) == 2 else None
            if not authorized(row, owner, self.allowed):
                await self.answer_callback(callback["id"], "无权限或任务不属于你。", True)
                return
            action, tid = parts
            if action == "engine" and row["status"] == "choice":
                self.store.update(tid, engine="whisper" if row["engine"] == "funasr" else "funasr")
                row = self.store.get(tid)
                if row["status_message"]:
                    try:
                        await asyncio.to_thread(self.telegram.call, "editMessageReplyMarkup", {"chat_id": row["chat"],
                             "message_id": row["status_message"], "reply_markup": self.choices(row)})
                    except Failure:
                        pass
                message = "已切换引擎"
            elif action in {"video", "raw", "both", "retry"}:
                # An old raw/both button cannot reconfigure a failed job.
                valid = (action == "retry" and row["status"] == "failed") or (action != "retry" and row["status"] == "choice")
                selected = row["polish"] if action == "retry" else action == "both"
                try:
                    queued = valid and self.store.enqueue(tid, owner, selected, int(os.getenv("QUEUE_LIMIT", "20")), mode=row["mode"] if action == "retry" else "video" if action == "video" else "transcript")
                    message = "已排队" if queued else "此任务已提交或已完成"
                except Failure as exc:
                    message = str(exc)
            else:
                message = "任务已提交，不能更改引擎"
            await self.answer_callback(callback["id"], message)
            if self.store.get(tid)["status"] == "queued":
                await self.notify(tid, "queued")
            return
        message = update.get("message")
        if not message or message.get("from", {}).get("id") not in self.allowed:
            return
        owner, chat = message["from"]["id"], message["chat"]["id"]
        text = message.get("text", "")
        if text.startswith(("/start", "/help")):
            reply = "发送 YouTube、X/Twitter 或抖音视频链接/分享文本。每条消息处理第一个有效链接。选择视频下载、原稿或原稿＋DeepSeek 整理稿，可在提交前切换引擎。/status 查看自己的任务。"
            await asyncio.to_thread(self.telegram.call, "sendMessage", {"chat_id": chat, "text": reply})
            return
        if text.startswith("/status"):
            rows = self.store.db.execute("SELECT id,status,stage,error FROM tasks WHERE owner=? AND chat=? ORDER BY created DESC LIMIT 10", (owner, chat)).fetchall()
            reply = "\n".join(f"{r['id']} {LABELS.get(r['stage'], r['stage'])}" for r in rows) or "暂无任务"
            choices = self.store.db.execute("SELECT * FROM tasks WHERE owner=? AND chat=? AND status='choice' ORDER BY created DESC LIMIT 1", (owner,chat)).fetchone()
            values={"chat_id":chat,"text":reply}
            if choices:values["reply_markup"]=self.choices(dict(choices))
            await asyncio.to_thread(self.telegram.call,"sendMessage",values)
            return
        try:
            target = parse_target(text)
        except (Failure, ValueError):
            await asyncio.to_thread(self.telegram.call, "sendMessage", {"chat_id": chat, "text": error_text("invalid_input", ERRORS)})
            return
        row = self.store.create(f"{chat}:{message['message_id']}", owner, chat, target)
        if row["status_message"] or row["status"] != "choice":
            return
        result = await asyncio.to_thread(self.telegram.call, "sendMessage", {"chat_id": chat,
                 "text": f"任务 {row['id']} · {target.platform}\n选择输出：下载视频不识别；原稿仅本地识别；DeepSeek 只接收转写文本。", "reply_markup": self.choices(row)})
        self.store.update(row["id"], status_message=result["message_id"])

    async def work(self):
        while True:
            row = self.store.claim()
            if row:
                await self.process(row)
            else:
                await asyncio.sleep(0.5)

    def normalize_update(self, update):
        out={"update_id":int(update["update_id"])}
        if update.get("callback_query"):
            cb=update["callback_query"]
            out["callback_query"]={"id":cb["id"],"from":{"id":cb["from"]["id"]},"data":cb.get("data","") if __import__("re").fullmatch(r"(?:video|raw|both|retry|engine):[a-f0-9]{32}",str(cb.get("data",""))) else ""}
        elif update.get("message"):
            m=update["message"];text=m.get("text","")
            if text.startswith(("/start","/help","/status")):text=text.split()[0]
            else:
                try:text=parse_target(text).url
                except (Failure,ValueError):text="invalid_video_address"
            out["message"]={"message_id":m["message_id"],"from":{"id":m.get("from",{}).get("id")},"chat":{"id":m["chat"]["id"]},"text":text[:200]}
        return out

    async def ingest(self, update):
        uid=update["update_id"]
        try:normalized=self.normalize_update(update)
        except (KeyError,TypeError,ValueError,AttributeError):
            self.store.inbox_put(uid,{"update_id":uid});self.store.inbox_finish(uid,"invalid_input");return
        receipt=self.store.inbox_put(uid,normalized)
        if receipt["state"] in {"done","failed"}:
            self.store.inbox_finish(uid,receipt["error"]);return
        payload=__import__('json').loads(receipt["payload"])
        error="update_attempts_exhausted" if receipt["attempts"]>=3 else None
        while receipt["attempts"]<3:
            with self.store.db:
                self.store.db.execute("UPDATE inbox SET attempts=attempts+1 WHERE update_id=?",(uid,))
            receipt["attempts"]+=1
            try:
                await self.handle(payload);error=None;break
            except Failure as exc:
                error=exc.code
                if error in {"send_forbidden","send_auth","send_invalid_request","invalid_input","disk_full","adapter_quota"}:break
                if receipt["attempts"]<3:await asyncio.sleep(2**(receipt["attempts"]-1))
            except Exception:
                error="internal_error";break
        self.store.inbox_finish(uid,error)
        if error:print("telegram_update_failed:"+error,flush=True)

    async def poll(self):
        while True:
            try:
                # Replay pending sanitized work before obtaining/acknowledging more remote updates.
                pending=self.store.db.execute("SELECT payload FROM inbox WHERE state='pending' ORDER BY update_id").fetchall()
                if pending:
                    for p in pending:await self.ingest(__import__('json').loads(p[0]))
                from .storage import protect
                protect(self.store.path.parent,kind="database")
                updates=await asyncio.to_thread(self.telegram.call,"getUpdates",{"offset":self.store.get_offset(),"timeout":25,"allowed_updates":["message","callback_query"]},timeout=35)
                for update in updates:
                    await self.ingest(update)
            except Exception:
                print("telegram_poll_or_storage_backoff",flush=True);await asyncio.sleep(5)


async def run():
    if os.getenv("BOT_PURPOSE") != "test":
        raise SystemExit("First release requires BOT_PURPOSE=test and an independent test bot")
    allowed = {int(s.strip()) for s in os.getenv("ALLOWED_USER_IDS", "").split(",") if s.strip()}
    if not allowed:
        raise SystemExit("ALLOWED_USER_IDS must not be empty")
    expected_id = int(os.getenv("EXPECTED_TEST_BOT_ID", "0"))
    if not expected_id:
        raise SystemExit("EXPECTED_TEST_BOT_ID is required")
    root = Path(os.getenv("DATA_ROOT", "/data/tasks"))
    db_root = Path(os.getenv("DB_ROOT", "/database"))
    db_root.mkdir(parents=True, exist_ok=True)
    singleton = (db_root / "manager.lock").open("a")
    try:
        fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another manager owns this database") from None
    telegram = Telegram(os.getenv("TELEGRAM_BOT_TOKEN", ""))
    me = await asyncio.to_thread(telegram.call, "getMe", {})
    if me["id"] != expected_id:
        raise SystemExit("Token does not belong to EXPECTED_TEST_BOT_ID; polling refused")
    remote=await asyncio.to_thread(json_request,os.getenv("GPU_URL","http://gpu:8080")+"/configuration")
    if remote.get("configs") != {engine:asr_config(engine) for engine in ("funasr","whisper")}:
        raise SystemExit("asr_config_mismatch; polling refused")
    store = Store(db_root / "tasks.sqlite3")
    store.recover()
    manager = Manager(store, root, Path(os.getenv("MODEL_ROOT", "/models")), telegram, allowed)
    from .adapter_common import enabled
    if enabled():
        from .adapter_broker import Broker, start_control
        manager.adapter = Broker(store)
        start_control(manager.adapter, asyncio.get_running_loop())
    await asyncio.gather(manager.poll(), manager.work())


if __name__ == "__main__":
    asyncio.run(run())
