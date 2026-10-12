import asyncio,json,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from v2t.core import Store,parse_target,Failure
from v2t.adapter_broker import Broker
from v2t.adapter_common import space

class Adapter(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp(prefix='v2t-adapter-tests-'));self.store=Store(self.root/'test.sqlite3');self.b=Broker(self.store)
 def row(self):
  r=self.store.create(uuid.uuid4().hex,1,1,parse_target('https://www.douyin.com/video/7692261748124177640'));self.store.enqueue(r['id'],1,False);return self.store.get(r['id'])
 async def claim(self,row):
  self.b.submit(row);r=await self.b.dispatch({'action':'claim','worker':'worker'});return {k:r[k] for k in ('task_id','generation','worker')}
 async def test_wait_does_not_block_heartbeat_or_unique_writer(self):
  row=self.row();p=await self.claim(row);waiter=asyncio.create_task(self.b.wait(row['id']));await asyncio.sleep(.01)
  result=await asyncio.wait_for(self.b.dispatch({'action':'heartbeat',**p}),.5);self.assertEqual(result['state'],'leased')
  self.store.event(row['id'],'other','success');self.b.change(row['id'],state='failed',error='download_failed')
  with self.assertRaises(Failure):await waiter
 async def test_queue_execution_deadlines_are_distinct(self):
  row=self.row();job=self.b.submit(row);self.assertIsNone(job['execution_deadline']);queued=job['queue_deadline'];p=await self.claim(row);job=self.b.get(row['id']);self.assertEqual(queued,job['queue_deadline']);self.assertGreater(job['execution_deadline'],queued)
 async def test_validating_survives_worker_lease_expiry_and_store_reopen(self):
  row=self.row();p=await self.claim(row);await self.b.dispatch({'action':'accept',**p});self.b.change(row['id'],lease_deadline=time.time()-100)
  self.store.db.close();self.store=Store(self.root/'test.sqlite3');self.b=Broker(self.store);self.b.refresh();self.assertEqual(self.b.get(row['id'])['state'],'validating')
  done=await self.b.dispatch({'action':'finish',**p,'completed_at':time.time(),'receipt':{'sha256':'a'*64}});self.assertEqual(done['state'],'complete')
  again=await self.b.dispatch({'action':'finish',**p,'completed_at':time.time(),'receipt':{'sha256':'a'*64}});self.assertEqual(done['receipt'],again['receipt'])
 async def test_expired_lease_old_generation_cannot_commit(self):
  row=self.row();p=await self.claim(row);self.b.change(row['id'],lease_deadline=time.time()-1)
  with self.assertRaises(Failure):await self.b.dispatch({'action':'heartbeat',**p})
  self.b.submit(row);q=await self.b.dispatch({'action':'claim','worker':'worker'});self.assertNotEqual(q['generation'],p['generation'])
  with self.assertRaises(Failure):await self.b.dispatch({'action':'accept',**p})
 async def test_disk_quota_and_minimum(self):
  (self.root/'retained').write_bytes(b'x'*4096)
  with self.assertRaises(Failure) as q:space(self.root,1,1,0)
  self.assertEqual(q.exception.code,'adapter_quota')
  with self.assertRaises(Failure) as q:space(self.root,1,2**63,2**63)
  self.assertEqual(q.exception.code,'disk_full')
 async def test_failure_ack_is_success_and_completion_immutable(self):
  row=self.row();p=await self.claim(row)
  ack=await self.b.dispatch({'action':'failure',**p,'code':'disk_full'});self.assertTrue(ack['accepted']);self.assertNotIn('error',ack)
  row=self.row();p=await self.claim(row);await self.b.dispatch({'action':'accept',**p})
  await self.b.dispatch({'action':'finish',**p,'completed_at':time.time(),'receipt':{}})
  ack=await self.b.dispatch({'action':'failure',**p,'code':'disk_full'});self.assertEqual(ack['state'],'complete')
 async def test_navigation_reader_tolerates_transient_context(self):
  from v2t.adapter_download import visible_verification
  class Page:
   def evaluate(self,*a):raise RuntimeError('local fixture context destroyed')
  self.assertFalse(visible_verification(Page()))
 def tearDown(self):self.store.db.close()
