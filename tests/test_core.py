import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v2t.core import (Failure, Store, asr_config, atomic_json, file_hash, fingerprint,
                      media_dir, parse_target, task_dir, validate_segments, write_transcript)
from v2t.download import build_fxtwitter_mp4_url, twitter
from v2t.douyin_data import _find_video, _video_urls, extract_aweme_id
from v2t.manager import Manager, authorized, cached_raw
from v2t.polish import chunks, config, polish
from v2t.worker import classify_error, funasr_segments


class Fixture(unittest.TestCase):
    def setUp(self):
        # No TemporaryDirectory auto-rmtree: only unlink individually known files in tearDown.
        self.root = Path(tempfile.mkdtemp(prefix="v2t-test-"))
        self.env = patch.dict(os.environ, {"MEDIA_ROOT": str(self.root / "media"), "DEEPSEEK_API_KEY": "test-not-a-real-key"})
        self.env.start()
        self.store = Store(self.root / "db" / "tasks.sqlite3")

    def tearDown(self):
        self.store.db.close()
        self.env.stop()
        # Deliberately retain test directories; no automatic bulk cleanup.

    def task(self, platform="youtube"):
        url = {"youtube": "https://youtu.be/BaW_jenozKc", "douyin": "https://www.douyin.com/video/7692261748124177640",
               "x": "https://x.com/example/status/1234567890123456789"}[platform]
        return self.store.create("one", 7, 9, parse_target(url))

    def artifacts(self, row):
        directory = task_dir(self.root / "results", row["id"])
        directory.mkdir(parents=True)
        source = media_dir(directory)
        source.mkdir(parents=True)
        (source / "media.bin").write_bytes(b"media")
        (source / "audio.wav").write_bytes(b"audio")
        media = {"sha256": file_hash(source / "media.bin"), "audio_sha256": file_hash(source / "audio.wav")}
        atomic_json(source / "media.json", media)
        cfg = asr_config(row["engine"])
        lock = {"config": cfg, "models": {}}
        modelroot = self.root / "models"
        atomic_json(modelroot / "models.lock.json", {row["engine"]: lock})
        raw = {"config": cfg, "segments": [{"start": 0, "end": 1, "text": "测试原稿。"}],
               "actual": {"engine": row["engine"], "device": "cuda", "compute_type": cfg["compute_type"]},
               "cache_key": fingerprint({"media": media["sha256"], "audio": media["audio_sha256"], "config": cfg, "weights": fingerprint(lock)})}
        atomic_json(directory / "raw.json", raw)
        return directory, modelroot, raw


class Core(Fixture):
    def test_share_and_platform_parsing(self):
        self.assertEqual(parse_target("分享文字 https://v.douyin.com/ABc123/ 复制打开").platform, "douyin")
        self.assertEqual(parse_target("https://www.youtube.com/shorts/BaW_jenozKc?feature=share").media_id, "BaW_jenozKc")
        self.assertEqual(parse_target("https://twitter.com/user/status/1234567890?s=1").platform, "x")
        for bad in ("https://evil.youtube.com/watch?v=BaW_jenozKc", "https://127.0.0.1/", "https://youtube.com@evil.test/watch?v=BaW_jenozKc"):
            with self.assertRaises(Failure): parse_target(bad)

    def test_dedupe_double_click_owner_and_queue_limit(self):
        row = self.task()
        again = self.store.create("one", 7, 9, parse_target(row["url"]))
        self.assertEqual(row["id"], again["id"])
        self.assertFalse(self.store.enqueue(row["id"], 8, False))
        self.assertTrue(self.store.enqueue(row["id"], 7, False))
        self.assertFalse(self.store.enqueue(row["id"], 7, True))
        row2 = self.store.create("two", 7, 9, parse_target(row["url"]))
        with self.assertRaises(Failure): self.store.enqueue(row2["id"], 7, False, limit=1)

    def test_restart_recovers_running_but_preserves_completed_and_failed(self):
        row = self.task()
        self.store.enqueue(row["id"], 7, False)
        self.store.claim()
        reopened = Store(self.root / "db" / "tasks.sqlite3")
        reopened.recover()
        self.assertEqual(reopened.get(row["id"])["status"], "queued")
        reopened.update(row["id"], status="done")
        reopened.recover()
        self.assertEqual(reopened.get(row["id"])["status"], "done")
        reopened.db.close()

    def test_cache_invalidation_content_model_and_precision(self):
        row = self.task()
        directory, modelroot, raw = self.artifacts(row)
        self.assertIsNotNone(cached_raw(directory, row["engine"], modelroot))
        with patch.dict(os.environ, {"WHISPER_REVISION": "changed"}):
            self.assertIsNone(cached_raw(directory, row["engine"], modelroot))
        (media_dir(directory) / "media.bin").write_bytes(b"different")
        self.assertIsNone(cached_raw(directory, row["engine"], modelroot))

    def test_target_matching_and_candidate_enumeration(self):
        detail = {"aweme_id": "123456789", "video": {"play_addr": {"url_list": ["https://cdn.test/a"]},
                    "bit_rate": [{"play_addr": {"height": 1080, "url_list": ["https://cdn.test/b", "https://cdn.test/a"]}}]}}
        self.assertEqual(_video_urls(detail), ["https://cdn.test/a", "https://cdn.test/b"])
        self.assertIsNone(_find_video({"recommended": detail}, "987654321"))
        self.assertEqual(_find_video({"nested": [detail]}, "123456789"), detail)
        self.assertEqual(extract_aweme_id("https://www.douyin.com/video/123456789"), "123456789")
        self.assertEqual(build_fxtwitter_mp4_url("123456789"), "https://fxtwitter.com/i/status/123456789.mp4")
        with patch("v2t.download.stream_file", side_effect=Failure("download_failed")):
            with self.assertRaises(Failure) as caught:
                twitter(parse_target("https://x.com/a/status/123456789"), self.root)
            self.assertEqual(caught.exception.code, "third_party_unavailable")

    def test_gpu_errors_and_funasr_all_results(self):
        self.assertEqual(classify_error(RuntimeError("CUDA out of memory")), "gpu_oom")
        self.assertEqual(classify_error(RuntimeError("libcudnn unavailable")), "gpu_unavailable")
        result = funasr_segments([{"sentence_info": [{"start": 0, "end": 1000, "text": "甲"}]},
                                 {"sentence_info": [{"start": 1000, "end": 2000, "text": "乙"}]}])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[-1]["end"], 2)
        with self.assertRaises(Failure): validate_segments([])
        with self.assertRaises(Failure): validate_segments([{"start": 0, "end": float('nan'), "text": "x"}])

    def test_utf8_original_and_timestamp(self):
        path = self.root / "原稿.md"
        write_transcript(path, [{"start": 3661.5, "end": 3662, "text": "涉外律师"}], {"engine": "funasr", "device": "cuda"})
        content = path.read_text(encoding="utf-8")
        self.assertIn("01:01:01.500", content)
        self.assertIn("涉外律师", content)

    def test_polish_budget_boundary(self):
        cfg = config()
        cfg["chunk_tokens"] = 100
        segs = [{"start": i, "end": i + 1, "text": "中" * 30} for i in range(3)]
        self.assertEqual(len(chunks(segs, cfg)), 3)
        with self.assertRaises(Failure): chunks([{"start": 0, "end": 1, "text": "中" * 100}], cfg)

    def test_polish_partial_resume_and_truncation(self):
        row = self.task()
        directory, _, raw = self.artifacts(row)
        raw["segments"] = [{"start": i, "end": i + 1, "text": "中" * 30} for i in range(3)]
        calls = []
        def failing(url, payload, **kw):
            calls.append(payload)
            if len(calls) > 1: raise Failure("polish_failed")
            return {"choices": [{"finish_reason": "stop", "message": {"content": "保留全部信息。"}}]}
        with patch.dict(os.environ, {"POLISH_CHUNK_TOKENS": "100"}):
            with self.assertRaises(Failure): polish(directory, raw, request=failing, sleep=lambda _: None)
            self.assertEqual(len(list((directory / "polish_blocks").glob("*.json"))), 1)
            resumed = []
            def success(url, payload, **kw):
                resumed.append(payload)
                return {"choices": [{"finish_reason": "stop", "message": {"content": "续跑。"}}]}
            result = polish(directory, raw, request=success, sleep=lambda _: None)
            self.assertEqual(len(resumed), 2)
            self.assertEqual(len(result["segments"]), 3)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                polish(directory, raw, request=lambda *a, **k: self.fail("cached blocks must not call API"))
            with patch.dict(os.environ, {"PROMPT_VERSION": "changed"}):
                with self.assertRaises(Failure) as caught:
                    polish(directory, raw, request=lambda *a, **k: {"choices": [{"finish_reason": "length", "message": {"content": "截断"}}]})
                self.assertEqual(caught.exception.code, "polish_truncated")


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.fail_once = False
        self.statuses = []
    def call(self, method, values, **kw):
        self.statuses.append((method, values))
        return {"message_id": 10}
    def send_document(self, chat, path, caption):
        if self.fail_once:
            self.fail_once = False
            raise Failure("send_failed")
        self.sent.append(path.name)
        return len(self.sent) + 100


class Flow(Fixture):
    def manager(self, modelroot, telegram, polisher=None):
        return Manager(self.store, self.root / "results", modelroot, telegram, {7},
                       service=lambda *a, **k: self.fail("completed artifacts must bypass downloader/GPU"),
                       polisher=polisher or (lambda *a: self.fail("original must not call DeepSeek")))

    def test_original_without_key(self):
        row = self.task()
        _, models, _ = self.artifacts(row)
        telegram = FakeTelegram()
        self.store.enqueue(row["id"], 7, False)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            asyncio.run(self.manager(models, telegram).process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["status"], "done")
        self.assertEqual(len(telegram.sent), 1)

    def test_send_failure_only_retries_delivery(self):
        row = self.task()
        _, models, _ = self.artifacts(row)
        telegram = FakeTelegram()
        telegram.fail_once = True
        manager = self.manager(models, telegram)
        self.store.enqueue(row["id"], 7, False)
        asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["error"], "send_failed")
        self.store.enqueue(row["id"], 7, False)
        asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["status"], "done")
        self.assertEqual(len(telegram.sent), 1)

    def test_polish_failure_preserves_original_and_sends_original_first(self):
        row = self.task("douyin")
        _, models, _ = self.artifacts(row)
        telegram = FakeTelegram()
        def failed(*a):
            self.assertEqual(len(telegram.sent), 1)
            raise Failure("polish_failed")
        manager = self.manager(models, telegram, failed)
        self.store.enqueue(row["id"], 7, True)
        asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["raw_sent"], 1)
        manager.polisher = lambda directory, raw: {"segments": raw["segments"]}
        self.store.enqueue(row["id"], 7, True)
        asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(len(telegram.sent), 2)
        self.assertIn("原稿", telegram.sent[0])
        self.assertIn("deepseek转写", telegram.sent[1])

    def test_button_whitelist_and_ownership(self):
        row = self.task()
        telegram = FakeTelegram()
        manager = self.manager(self.root, telegram)
        for owner in [8, 99]:
            asyncio.run(manager.handle({"callback_query": {"id": "cb", "from": {"id": owner}, "data": "both:" + row["id"]}}))
        self.assertEqual(self.store.get(row["id"])["status"], "choice")
        asyncio.run(manager.handle({"callback_query": {"id": "cb", "from": {"id": 7}, "data": "engine:" + row["id"]}}))
        self.assertEqual(self.store.get(row["id"])["engine"], "funasr")
        for _ in range(2):
            asyncio.run(manager.handle({"callback_query": {"id": "cb", "from": {"id": 7}, "data": "both:" + row["id"]}}))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks WHERE status='queued'").fetchone()[0], 1)

    def test_expired_callback_does_not_replay_committed_action(self):
        row = self.task()
        telegram = FakeTelegram()
        original = telegram.call
        def expired(method, values, **kw):
            if method == "answerCallbackQuery":
                raise Failure("send_failed")
            return original(method, values, **kw)
        telegram.call = expired
        manager = self.manager(self.root, telegram)
        callback = {"callback_query": {"id": "expired", "from": {"id": 7}, "data": "raw:" + row["id"]}}
        asyncio.run(manager.handle(callback))
        asyncio.run(manager.handle(callback))
        self.assertEqual(self.store.get(row["id"])["status"], "queued")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)

    def test_polished_send_retry_skips_completed_llm_without_key(self):
        row = self.task()
        directory, models, raw = self.artifacts(row)
        polish(directory, raw, request=lambda *a, **k: {"choices": [{"finish_reason": "stop", "message": {"content": "测试整理稿。"}}]})
        telegram = FakeTelegram()
        original_send = telegram.send_document
        failed = [False]
        def send(chat, path, caption):
            if "deepseek转写" in path.name and not failed[0]:
                failed[0] = True
                raise Failure("send_failed")
            return original_send(chat, path, caption)
        telegram.send_document = send
        manager = self.manager(models, telegram, lambda *a: self.fail("completed polish must not run again"))
        self.store.enqueue(row["id"], 7, True)
        asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["error"], "send_failed")
        self.store.enqueue(row["id"], 7, True)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            asyncio.run(manager.process(self.store.claim()))
        self.assertEqual(self.store.get(row["id"])["status"], "done")
        self.assertEqual(len(telegram.sent), 2)


if __name__ == "__main__":
    unittest.main()
