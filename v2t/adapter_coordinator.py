"""Explicit test-only coordinator: identical actor, no Telegram/ASR/DeepSeek."""
import asyncio,fcntl,os
from pathlib import Path
from .core import Store
from .adapter_broker import Broker,start_control

async def run():
 if os.getenv('ADAPTER_TEST_MODE')!='1' or os.getenv('WINDOWS_ADAPTER_ENABLED')!='1':raise SystemExit('explicit adapter test mode required')
 root=Path(os.environ['DB_ROOT']);root.mkdir(parents=True,exist_ok=True)
 lock=(root/'manager.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 store=Store(root/'tasks.sqlite3');broker=Broker(store);start_control(broker,asyncio.get_running_loop())
 while True:broker.refresh();await asyncio.sleep(.2)
if __name__=='__main__':asyncio.run(run())
