import asyncio,json,os,ssl,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_core import Fixture,FakeTelegram
from v2t.core import Failure,parse_target
from v2t.manager import Manager
from v2t.browser_policy import browser_url
class Fixes(Fixture):
 def manager(self,t):return Manager(self.store,self.root/'results',self.root/'models',t,{7})
 def message(self,uid,text='https://youtu.be/BaW_jenozKc'):return {'update_id':uid,'message':{'from':{'id':7},'chat':{'id':9},'message_id':uid,'text':text}}
 def test_permanent_update_failure_does_not_block_following_links_callbacks(self):
  t=FakeTelegram();original=t.call;attempts=[0]
  def call(method,values,**kw):
   if method=='sendMessage' and '选择输出' in values.get('text',''):
    attempts[0]+=1
    if attempts[0]==1:raise Failure('send_forbidden')
   return original(method,values,**kw)
  t.call=call;m=self.manager(t);asyncio.run(m.ingest(self.message(1)));asyncio.run(m.ingest(self.message(2)))
  row=dict(self.store.db.execute('select * from tasks order by created desc limit 1').fetchone())
  cb={'update_id':3,'callback_query':{'id':'cb','from':{'id':7},'data':'raw:'+row['id']}}
  asyncio.run(m.ingest(cb));asyncio.run(m.ingest(self.message(1)));asyncio.run(m.ingest(cb))
  self.assertEqual(self.store.get_offset(),4);self.assertEqual(self.store.get(row['id'])['status'],'queued');self.assertEqual(self.store.db.execute('select count(*) from tasks').fetchone()[0],2)
  failed=self.store.db.execute('select state,error,attempts from inbox where update_id=1').fetchone();self.assertEqual(tuple(failed),('failed','send_forbidden',1))
 def test_transient_retry_bounded_and_third_attempt_success(self):
  t=FakeTelegram();original=t.call;n=[0]
  def call(method,values,**kw):
   n[0]+=1
   if n[0]<3:raise Failure('send_failed')
   return original(method,values,**kw)
  t.call=call;m=self.manager(t)
  with patch('v2t.manager.asyncio.sleep',return_value=None):asyncio.run(m.ingest(self.message(8)))
  self.assertEqual(n[0],3);self.assertEqual(self.store.db.execute('select state from inbox').fetchone()[0],'done')
 def test_pending_receipt_and_task_effect_replay_dedupe(self):
  m=self.manager(FakeTelegram());u=self.message(12);self.store.inbox_put(12,m.normalize_update(u));self.store.create('9:12',7,9,parse_target(u['message']['text']))
  asyncio.run(m.ingest(u));self.assertEqual(self.store.db.execute('select count(*) from tasks').fetchone()[0],1);self.assertEqual(self.store.get_offset(),13)
 def test_browser_private_and_redirect_destinations_blocked(self):
  def resolve(host,port,**kwargs):return [(2,1,6,'',( '127.0.0.1' if host=='www.douyin.com' else '1.1.1.1',port))]
  for url in ['http://127.0.0.1/','http://192.168.1.2/','https://www.douyin.com/','https://evil.example/']:
   with self.assertRaises(Failure):browser_url(url,True,resolve)
  self.assertEqual(browser_url('https://v.douyin.com/link',False,resolve),'https://v.douyin.com/link')
 def test_worker_waits_on_transport_not_on_auth(self):
  from v2t.adapter_worker import Worker
  w=object.__new__(Worker);w.config={'cert':'fixture','reconnect_max_seconds':4};w.client=type('Client',(),{})();w.client.credentials=lambda:{'cert':'fixture'}
  values=[Failure('adapter_network'),Failure('service_unavailable'),{'idle':False,'task_id':'a'*32}]
  def call(*args):
   value=values.pop(0)
   if isinstance(value,Failure):raise value
   return value
  w.client.call=call;w.execute=lambda _: {'state':'complete'}
  with patch('v2t.adapter_worker.cert_remaining',return_value=10000),patch('v2t.adapter_worker.time.sleep') as sleep:self.assertEqual(w.run(1),0);self.assertEqual([x.args[0] for x in sleep.call_args_list],[1,2])
  w.client.call=lambda *args: (_ for _ in ()).throw(Failure('adapter_auth'))
  with patch('v2t.adapter_worker.cert_remaining',return_value=10000):self.assertEqual(w.run(1),1)
 def test_douyin_disabled_explicit_no_download_service(self):
  m=self.manager(FakeTelegram());row=self.task('douyin');m.service=lambda *a,**k:self.fail('no Linux fallback')
  with self.assertRaises(Failure) as e:asyncio.run(m.download(row))
  self.assertEqual(e.exception.code,'adapter_disabled')
 def test_storage_floor_reserves_database_space(self):
  from v2t.storage import protect
  with patch('v2t.storage.shutil.disk_usage',return_value=type('Usage',(),{'free':100})()):
   with self.assertRaises(Failure) as e:protect(self.root,kind='database')
   self.assertEqual(e.exception.code,'disk_full')
 def test_x_index_retained(self):
  target=parse_target('https://x.com/interr_x/status/2109130078777118856/video/2?s=46');self.assertEqual(target.video_index,2);self.assertTrue(target.url.endswith('/video/2'))

 def test_malformed_update_isolated_and_offset_durable(self):
  m=self.manager(FakeTelegram());asyncio.run(m.ingest({'update_id':30,'message':{'text':None}}));asyncio.run(m.ingest(self.message(31)))
  self.assertEqual(self.store.get_offset(),32);self.assertEqual(self.store.db.execute('select error from inbox where update_id=30').fetchone()[0],'invalid_input')

 def test_x_mixed_attachment_position_not_video_list_position(self):
  from v2t.download import indexed_twitter_video
  item={'media':{'all':[{'type':'photo','url':'https://example.invalid/photo'},{'type':'video','url':'https://video.twimg.com/second.mp4'}],'videos':[{'url':'https://video.twimg.com/second.mp4'}]}}
  self.assertEqual(indexed_twitter_video(item,2),'https://video.twimg.com/second.mp4')
  with self.assertRaises(Failure):indexed_twitter_video(item,1)

 def test_temporary_directory_disappears_during_quota_scan(self):
  from v2t.adapter_common import usage
  def walk(root,onerror,followlinks):
   onerror(FileNotFoundError('browser directory vanished'))
   yield str(self.root),[],['vanished-file']
  with patch('v2t.adapter_common.os.walk',side_effect=walk):self.assertEqual(usage(self.root),0)
  def denied(root,onerror,followlinks):
   onerror(PermissionError('unreadable directory'))
   yield str(self.root),[],[]
  with patch('v2t.adapter_common.os.walk',side_effect=denied):
   with self.assertRaises(Failure):usage(self.root)
 def test_cleanup_error_does_not_override_completed_download(self):
  from v2t.adapter_download import close_browser_resources
  broken=type('ClosedBrowser',(),{'close':lambda _:(_ for _ in ()).throw(RuntimeError('browser gone'))})();second=type('Context',(),{'close':lambda _:None})()
  def completed():
   try:return 'complete-media'
   finally:close_browser_resources(broken,second)
  self.assertEqual(completed(),'complete-media')
