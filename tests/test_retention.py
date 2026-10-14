import asyncio,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from v2t.core import Store,parse_target,Failure
from v2t.retention import eligible,remove_one

class Retention(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp(prefix='v2t-retention-test-'));self.store=Store(self.root/'tasks.sqlite3');self.env=patch.dict(os.environ,MEDIA_RETENTION_DAYS='3');self.env.start();self.old=time.time()-4*86400
 def tearDown(self):self.store.db.close();self.env.stop()
 def row(self,status,age):
  r=self.store.create(str(time.time_ns()),7,9,parse_target('https://youtu.be/BaW_jenozKc'))
  with self.store.db:self.store.db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?',(status,time.time()-age*86400,r['id']))
  return r['id']
 def file(self,tid,name,old=True):
  p=self.root/'media'/tid/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture');os.utime(p,(self.old,self.old)) if old else None;return p
 def test_only_old_completed_tasks(self):
  keep=[self.row(s,4) for s in ['choice','queued','running','failed']]+[self.row('done',2)];wanted=self.row('done',4)
  self.assertEqual([r['id'] for r in eligible(self.store)],[wanted])
 def test_deletes_one_media_preserves_text_metadata_models_and_directories(self):
  t=self.row('done',4);media=self.file(t,'media.bin');audio=self.file(t,'audio.wav');text=self.file(t,'原稿.md');meta=self.file(t,'media.json');model=self.file(t,'weights.bin')
  r=remove_one(self.root/'media',t,self.old+1);self.assertEqual(r['removed'],1);self.assertFalse(media.exists());self.assertTrue(audio.exists())
  remove_one(self.root/'media',t,self.old+1);self.assertFalse(audio.exists());self.assertTrue(all(p.exists() for p in [text,meta,model]));self.assertTrue(text.parent.is_dir());self.assertTrue(remove_one(self.root/'media',t)['complete'])
 def test_recent_file_deferred_even_in_old_task(self):
  t=self.row('done',4);f=self.file(t,'media.complete',False);r=remove_one(self.root/'media',t,time.time()-3*86400);self.assertTrue(r['deferred']);self.assertFalse(r['complete']);self.assertTrue(f.exists())
 def test_path_escape_and_symlink_rejected(self):
  with self.assertRaises(Failure):remove_one(self.root,'../outside')
  t=self.row('done',4);external=self.root/'outside.bin';external.write_bytes(b'keep');d=self.root/'media'/t;d.mkdir(parents=True);(d/'media.bin').symlink_to(external)
  with self.assertRaises(Failure):remove_one(self.root/'media',t)
  self.assertTrue(external.exists())
 def test_adapter_active_lease_protected_and_worker_identity_filtered(self):
  from v2t.adapter_broker import Broker
  b=Broker(self.store);good=self.row('done',4);active=self.row('done',4)
  with self.store.db:
   self.store.db.execute("INSERT INTO adapter_jobs(task_id,state,worker) VALUES(?,?,?)",(good,'complete','worker-a'))
   self.store.db.execute("INSERT INTO adapter_jobs(task_id,state,worker) VALUES(?,?,?)",(active,'uploading','worker-a'))
  self.assertEqual([r['id'] for r in eligible(self.store)],[good]);self.assertEqual([r['id'] for r in eligible(self.store,'worker-a')],[good]);self.assertEqual(eligible(self.store,'worker-b'),[])
  response=asyncio.run(b.dispatch({'action':'retention','worker':'worker-a'}));self.assertEqual(response['tasks'][0]['task_id'],good)
 def test_retention_disabled_and_already_cleaned_not_repeated(self):
  t=self.row('done',4)
  self.store.db.execute('CREATE TABLE media_retention(task_id TEXT PRIMARY KEY,cleaned REAL,bytes_removed INTEGER)');self.store.db.execute('INSERT INTO media_retention VALUES(?,?,?)',(t,time.time(),7));self.store.db.commit();self.assertEqual(eligible(self.store),[])
  with patch.dict(os.environ,MEDIA_RETENTION_DAYS='0'):self.assertEqual(eligible(self.store,'worker-a'),[])

 def test_worker_rechecks_policy_before_deleting_cached_candidate(self):
  from v2t.adapter_worker import Worker
  t=self.row('done',4);f=self.file(t,'media.complete');w=object.__new__(Worker);w.root=self.root/'media';w.retention_queue=[t];w.retention_due=0;w.retention_seconds=3*86400
  w.client=type('Client',(),{'call':lambda _,route,p:{'authorized':False,'seconds':0}})();w.cleanup_media();self.assertTrue(f.exists());self.assertEqual(w.retention_queue,[])
