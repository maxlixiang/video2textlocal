"""Container crash/restart probe with real ASR cache and simulated Telegram acknowledgement.

No Telegram token or DeepSeek call. Does not fabricate a DeepSeek result.
"""
import argparse
import asyncio
import os
from pathlib import Path

from .core import Failure, Store, atomic_json, parse_target
from .manager import Manager


class ReceiptOnly:
    def __init__(self):
        self.documents = 0

    def call(self, *args, **kwargs):
        return {"message_id": 700}

    def send_document(self, *args, **kwargs):
        self.documents += 1
        return 701


async def run(task_id):
    store = Store(Path("/database/recovery-probe.sqlite3"))
    row = store.get(task_id)
    first = row is None
    if first:
        row = store.create("recovery-probe", 7, 9, parse_target("https://www.youtube.com/watch?v=G14CnqM70Cw"))
        with store.db:
            store.db.execute("UPDATE tasks SET id=? WHERE id=?", (task_id, row["id"]))
        store.enqueue(task_id, 7, True)
    else:
        assert row["status"] == "running" and row["raw_sent"] == 1
        store.recover()
        assert store.get(task_id)["status"] == "queued"
    telegram = ReceiptOnly()
    def no_service(*args, **kwargs):
        raise AssertionError("download/GPU service must not run during cache recovery")
    def polisher(*args, **kwargs):
        if first:
            atomic_json(Path("/verification/recovery-phase1.json"), {"injected_crash": True, "exit_code": 87,
                        "confirmed_raw_documents": 1, "telegram_simulated": True})
            os._exit(87)
        raise Failure("deepseek_missing")
    manager = Manager(store, Path("/results"), Path("/models"), telegram, {7}, service=no_service, polisher=polisher)
    await manager.process(store.claim())
    row = store.get(task_id)
    assert row["status"] == "failed" and row["error"] == "deepseek_missing"
    assert telegram.documents == 0 and row["raw_sent"] == 1
    assert store.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1
    atomic_json(Path("/verification/container-recovery.json"), {"status": "passed", "restart_recovered": True,
                "confirmed_raw_not_resent": True, "new_document_sends": 0, "download_or_gpu_calls": 0,
                "telegram_simulated": True, "deepseek_not_called": True, "final_error": row["error"]})
    print("container recovery passed; Telegram acknowledgement simulated, DeepSeek not called")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    asyncio.run(run(parser.parse_args().task_id))
