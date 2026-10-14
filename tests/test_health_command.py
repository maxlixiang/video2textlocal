import asyncio,time,os
from unittest.mock import patch
from test_core import Fixture,FakeTelegram
from v2t.core import asr_config,Failure
from v2t.manager import Manager
from v2t.adapter_broker import Broker

class HealthCommand(Fixture):
 def manager(self,t=None,fail=False):
  self.calls=[]
  def service(url,*a,**k):
   self.calls.append(url)
   if fail:raise Failure('service_unavailable')
   if url.endswith('/configuration'):return {'configs':{e:asr_config(e) for e in ('funasr','whisper')}}
   return {'ready':True,'warnings':[]}
  return Manager(self.store,self.root/'results',self.root/'models',t or FakeTelegram(),{7},service=service)
 def command(self,m,owner=7):return asyncio.run(m.ingest({'update_id':17,'message':{'from':{'id':owner},'chat':{'id':9},'message_id':17,'text':'/check'}}))
 def test_command_received_and_deduped_without_creating_task(self):
  t=FakeTelegram();m=self.manager(t)
  self.command(m);self.command(m)
  messages=[v for method,v in t.statuses if method=='sendMessage']
  self.assertEqual(len(messages),1);self.assertIn('健康检查',messages[0]['text'])
  self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
  self.assertTrue(all(u.endswith(('/health','/configuration')) for u in self.calls))
 def test_unauthorized_no_probe_or_reply(self):
  t=FakeTelegram();m=self.manager(t);self.command(m,8);self.assertFalse(self.calls);self.assertFalse(t.statuses)
 def test_worker_recent_stale_and_disabled(self):
  m=self.manager();m.adapter=Broker(self.store)
  with self.store.db:self.store.db.execute('INSERT INTO adapter_workers VALUES(?,?)',('fixture-worker',time.time()))
  with patch.dict(os.environ,{'WINDOWS_ADAPTER_ENABLED':'1'}):
   self.assertIn('进程：在线',asyncio.run(m.check_services()))
   with self.store.db:self.store.db.execute('UPDATE adapter_workers SET seen=?',(time.time()-120,))
   self.assertIn('进程：离线',asyncio.run(m.check_services()))
  with patch.dict(os.environ,{'WINDOWS_ADAPTER_ENABLED':'0'}):self.assertIn('适配器未启用',asyncio.run(m.check_services()))
 def test_unavailable_services_and_missing_key_are_clear(self):
  m=self.manager(fail=True)
  with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'','WINDOWS_ADAPTER_ENABLED':'1'}):
   text=asyncio.run(m.check_services());self.assertIn('下载服务：异常',text);self.assertIn('抖音下载：暂不可用',text);self.assertIn('未配置密钥',text)
 def test_config_mismatch_does_not_claim_gpu_ready(self):
  m=self.manager();m.service=lambda url,**k:{'configs':{}} if url.endswith('/configuration') else {'ready':True}
  self.assertIn('配置不一致',asyncio.run(m.check_services()))
 def test_active_heartbeat_updates_worker_liveness(self):
  r=self.task('douyin');self.store.enqueue(r['id'],7,False);b=Broker(self.store);b.submit(self.store.get(r['id']))
  job=asyncio.run(b.dispatch({'action':'claim','worker':'fixture-worker'}))
  with self.store.db:self.store.db.execute('UPDATE adapter_workers SET seen=?',(time.time()-120,))
  asyncio.run(b.dispatch({'action':'heartbeat','worker':'fixture-worker','task_id':job['task_id'],'generation':job['generation']}))
  seen=self.store.db.execute('SELECT seen FROM adapter_workers').fetchone()[0];self.assertLess(time.time()-seen,2)
