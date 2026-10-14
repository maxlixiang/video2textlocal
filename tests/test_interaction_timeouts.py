import asyncio,time
from unittest.mock import patch
from test_core import Fixture,FakeTelegram
from v2t.core import Store,parse_target,Failure
from v2t.manager import Manager

class Interaction(Fixture):
 def manager(self,t=None,polisher=None):return Manager(self.store,self.root/'results',self.root/'models',t or FakeTelegram(),{7},polisher=polisher)
 def age(self,row,seconds):
  with self.store.db:self.store.db.execute('UPDATE tasks SET created=? WHERE id=?',(time.time()-seconds,row['id']))
 def status(self,m,owner=7):asyncio.run(m.handle({'message':{'from':{'id':owner},'chat':{'id':9},'message_id':8,'text':'/status'}}))
 def callback(self,m,row,action='raw',owner=7):asyncio.run(m.handle({'callback_query':{'id':'cb','from':{'id':owner},'data':action+':'+row['id']}}))
 def test_exact_deadline_and_no_enqueue_after_expiry(self):
  r=self.task();created=r['created']
  self.assertFalse(self.store.expire_choice(r['id'],created+119.9))
  self.assertTrue(self.store.expire_choice(r['id'],created+120))
  self.assertFalse(self.store.enqueue(r['id'],7,False))
 def test_late_callback_rejected_without_timer(self):
  r=self.task();self.age(r,121);t=FakeTelegram();self.callback(self.manager(t),r)
  self.assertEqual(self.store.get(r['id'])['status'],'expired')
  self.assertIn('重新发送',t.statuses[-1][1]['text'])
 def test_engine_switch_does_not_extend_deadline(self):
  r=self.task();self.age(r,119);before=self.store.get(r['id'])['created'];m=self.manager()
  self.callback(m,r,'engine');self.assertEqual(self.store.get(r['id'])['created'],before)
  self.assertTrue(self.store.expire_choice(r['id'],before+120))
 def test_timeout_notice_persistent_dedup_and_restart(self):
  r=self.task();self.age(r,121);self.store.update(r['id'],status_message=10)
  t=FakeTelegram();m=self.manager(t);asyncio.run(m.expire_choices_once());asyncio.run(m.expire_choices_once())
  notices=[v for method,v in t.statuses if method=='sendMessage'];self.assertEqual(len(notices),1)
  self.assertIn('本次请求已取消',notices[0]['text']);self.assertEqual(self.store.get(r['id'])['status'],'expired')
  reopened=Store(self.store.path);reopened.recover();self.assertEqual(reopened.get(r['id'])['status'],'expired');reopened.db.close()
 def test_timer_does_not_cancel_submitted_work(self):
  r=self.task();self.store.enqueue(r['id'],7,False);self.age(r,180)
  asyncio.run(self.manager().expire_choices_once());self.assertEqual(self.store.get(r['id'])['status'],'queued')
 def test_notice_permanent_failure_does_not_loop(self):
  r=self.task();self.age(r,121);t=FakeTelegram();t.call=lambda *a,**k:(_ for _ in ()).throw(Failure('send_forbidden'))
  m=self.manager(t);asyncio.run(m.expire_choices_once());asyncio.run(m.expire_choices_once())
  n=self.store.db.execute('SELECT state,attempts FROM choice_notices').fetchone();self.assertEqual(tuple(n),('failed',1))
 def test_status_standby_and_owner_filter(self):
  r=self.task();self.store.update(r['id'],status='failed',stage='failed',error='download_failed')
  self.store.create('other',8,9,parse_target(r['url']))
  t=FakeTelegram();m=self.manager(t);self.status(m);text=t.statuses[-1][1]['text']
  self.assertIn('待命',text);self.assertIn('下载失败',text);self.assertNotIn('等待选择',text)
  count=len(t.statuses);self.status(m,8);self.assertEqual(count,len(t.statuses))
 def test_status_multiple_stages_and_remaining(self):
  r=self.task();r2=self.store.create('second',7,9,parse_target(r['url']));self.store.update(r2['id'],status='running',stage='polish')
  t=FakeTelegram();self.status(self.manager(t));text=t.statuses[-1][1]['text']
  for word in ('剩余','等待选择','DeepSeek 整理','仍可发送'):self.assertIn(word,text)
 def test_polish_wait_notice_before_call_and_once_on_retry(self):
  r=self.task();_,models,raw=self.artifacts(r);t=FakeTelegram()
  def polisher(*args):
   self.assertEqual(len(t.sent),1)
   self.assertTrue(any(method=='sendMessage' and '原稿已发送' in v.get('text','') for method,v in t.statuses))
   raise Failure('polish_failed')
  m=Manager(self.store,self.root/'results',models,t,{7},polisher=polisher)
  self.store.enqueue(r['id'],7,True)
  with patch('v2t.manager.cached_polished',return_value=None):
   asyncio.run(m.process(self.store.claim()));self.store.enqueue(r['id'],7,True);asyncio.run(m.process(self.store.claim()))
  notices=[v for method,v in t.statuses if method=='sendMessage' and '原稿已发送' in v.get('text','')]
  self.assertEqual(len(notices),1);self.assertEqual(len(t.sent),1)
