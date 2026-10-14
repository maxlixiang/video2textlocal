"""Manager-owned SQLite actor. HTTP threads dispatch to the event loop, never write DB."""
import asyncio,concurrent.futures,hmac,json,os,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .core import Failure,parse_target
from .adapter_common import key,ident

class Broker:
 def __init__(self,store):
  self.store=store;self.db=store.db
  self.queue_ttl=int(os.getenv('ADAPTER_QUEUE_SECONDS','300'));self.execution_ttl=int(os.getenv('ADAPTER_EXECUTION_SECONDS','600'));self.lease_ttl=int(os.getenv('ADAPTER_LEASE_SECONDS','45'));self.validate_ttl=int(os.getenv('ADAPTER_VALIDATION_SECONDS','180'))
  self.db.executescript('''CREATE TABLE IF NOT EXISTS adapter_jobs(task_id TEXT PRIMARY KEY,url TEXT,input_id TEXT,state TEXT,generation TEXT,worker TEXT,queued REAL,queue_deadline REAL,execution_deadline REAL,lease_deadline REAL,validation_deadline REAL,completed_at REAL,error TEXT,receipt TEXT); CREATE TABLE IF NOT EXISTS adapter_workers(worker TEXT PRIMARY KEY,seen REAL);''')
 def get(self,tid):
  r=self.db.execute('SELECT * FROM adapter_jobs WHERE task_id=?',(tid,)).fetchone()
  if not r: return None
  job=dict(r);row=self.store.get(tid);job["mode"]=row.get("mode","transcript") if row else "transcript";return job
 def change(self,tid,**fields):
  with self.db:self.db.execute('UPDATE adapter_jobs SET '+','.join(k+'=?' for k in fields)+' WHERE task_id=?',(*fields.values(),tid))
 def refresh(self):
  now=time.time()
  with self.db:
   self.db.execute("UPDATE adapter_jobs SET state='failed',error='adapter_queue_expired' WHERE state='waiting' AND queue_deadline<?",(now,))
   self.db.execute("UPDATE adapter_jobs SET state='failed',error='adapter_lease_expired' WHERE state IN ('leased','uploading') AND (lease_deadline<? OR execution_deadline<?)",(now,now))
   self.db.execute("UPDATE adapter_jobs SET state='failed',error='timeout' WHERE state='validating' AND validation_deadline<?",(now,))
 def submit(self,row):
  tid=ident(row['id']);old=self.get(tid)
  if old and old['state']!='failed':return old
  queued=row.get('queued_at') or time.time();target=parse_target(row['url'])
  if target.platform!='douyin':raise Failure('invalid_input')
  with self.db:
   self.db.execute('INSERT OR REPLACE INTO adapter_jobs(task_id,url,input_id,state,generation,queued,queue_deadline) VALUES(?,?,?,?,?,?,?)',(tid,target.url,target.media_id,'waiting',uuid.uuid4().hex,queued,queued+self.queue_ttl))
  return self.get(tid)
 def checked(self,p,validating=False):
  self.refresh();r=self.get(ident(p['task_id']))
  if not r or r['generation']!=p.get('generation') or r['worker']!=p.get('worker'):raise Failure('adapter_lease_expired')
  allowed={'leased','uploading','validating','complete'} if validating else {'leased','uploading'}
  if r['state'] not in allowed:raise Failure(r['error'] or 'adapter_lease_expired')
  return r
 async def dispatch(self,p):
  action=p['action'];worker=p.get('worker');self.refresh()
  if action=='retention_check':
   from .retention import seconds
   ttl=seconds();tid=ident(p['task_id']);row=self.store.get(tid);job=self.get(tid)
   authorized=bool(ttl and row and row['status']=='done' and row['updated']<=time.time()-ttl and job and job['worker']==worker and job['state']=='complete')
   return {'authorized':authorized,'seconds':ttl}
  if action=='retention':
   from .retention import eligible,seconds
   cursor=p.get('cursor','')
   if cursor:ident(cursor)
   rows=eligible(self.store,worker=worker,cursor=cursor)
   return {'tasks':[{'task_id':r['id'],'completed_at':r['updated']} for r in rows],'seconds':seconds(),'next_cursor':rows[-1]['id'] if rows else ''}
  if action=='test_retry':
   if os.getenv('ADAPTER_TEST_MODE')!='1':raise Failure('invalid_input')
   row=self.store.get(ident(p['task_id']))
   if not row or row['owner']!=0 or row['chat']!=0:raise Failure('invalid_input')
   old=self.get(row['id'])
   if old and old['state']!='failed':return old
   self.store.update(row['id'],status='failed')
   self.store.enqueue(row['id'],0,False,100)
   return self.submit(self.store.get(row['id']))
  if action=='test_submit':
   if os.getenv('ADAPTER_TEST_MODE')!='1':raise Failure('invalid_input')
   target=parse_target(p['url']);row=self.store.create('adapter-test:'+p['request_id'],0,0,target);self.store.enqueue(row['id'],0,False,100);row=self.store.get(row['id']);return self.submit(row)
  if action=='claim':
   if not isinstance(worker,str) or not 1<=len(worker)<=64:raise Failure('adapter_auth')
   with self.db:self.db.execute('INSERT OR REPLACE INTO adapter_workers VALUES(?,?)',(worker,time.time()))
   active=self.db.execute("SELECT * FROM adapter_jobs WHERE worker=? AND state IN ('leased','uploading','validating','complete') AND state!='complete' LIMIT 1",(worker,)).fetchone()
   if active:return self.get(active["task_id"])
   if self.db.execute("SELECT 1 FROM adapter_jobs WHERE state IN ('leased','uploading','validating')").fetchone():return {'idle':True}
   r=self.db.execute("SELECT * FROM adapter_jobs WHERE state='waiting' ORDER BY queued LIMIT 1").fetchone()
   if not r:return {'idle':True}
   self.change(r['task_id'],state='leased',worker=worker,execution_deadline=time.time()+self.execution_ttl,lease_deadline=time.time()+self.lease_ttl)
   return self.get(r['task_id'])
  if action in ('heartbeat','check','start','accept','status'):
   r=self.checked(p,validating=action in ('heartbeat','status','accept'))
   if action=='heartbeat':
    with self.db:self.db.execute('INSERT OR REPLACE INTO adapter_workers VALUES(?,?)',(worker,time.time()))
   if action=='heartbeat' and r['state'] in ('leased','uploading'):self.change(r['task_id'],lease_deadline=min(time.time()+self.lease_ttl,r['execution_deadline']))
   if action=='start':self.change(r['task_id'],state='uploading')
   if action=='accept' and r['state'] in ('leased','uploading'):self.change(r['task_id'],state='validating',validation_deadline=time.time()+self.validate_ttl)
   return self.get(r['task_id'])
  if action=='finish':
   r=self.get(ident(p['task_id']))
   if not r or r['generation']!=p['generation'] or r['worker']!=worker:raise Failure('adapter_lease_expired')
   if r['state']=='complete':return r
   if not r['validation_deadline'] or float(p['completed_at'])>r['validation_deadline']:raise Failure('timeout')
   if r['state'] not in ('validating','failed'):raise Failure('adapter_lease_expired')
   self.change(r['task_id'],state='complete',error=None,completed_at=p['completed_at'],receipt=json.dumps(p['receipt']))
   return self.get(r['task_id'])
  if action=='failure':
   r=self.checked(p,validating=True)
   if r['state']=='complete':return {'accepted':True,'state':'complete'}
   from .core import ERRORS
   code=p.get('code','download_failed')
   if code not in ERRORS:raise Failure('invalid_input')
   self.change(r['task_id'],state='failed',error=code);return {'accepted':True,'state':'failed'}
  if action=='wait':return await self.wait(p['task_id'])
  raise Failure('invalid_input')
 async def wait(self,tid):
  started=time.monotonic()
  while True:
   self.refresh();r=self.get(tid)
   if not r:raise Failure('invalid_input')
   if r['state']=='complete':return {'complete':True,'receipt':json.loads(r['receipt'])}
   if r['state']=='failed':raise Failure(r['error'])
   if r['state']=='waiting' and time.monotonic()-started>10:
    available=self.db.execute('SELECT 1 FROM adapter_workers WHERE seen>?',(time.time()-self.lease_ttl,)).fetchone()
    if not available:self.change(tid,state='failed',error='adapter_unavailable');raise Failure('adapter_unavailable')
   await asyncio.sleep(.2)

def start_control(broker,loop):
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_POST(self):
   out={};status=200
   try:
    if not hmac.compare_digest(self.headers.get('X-Adapter-Key',''),key()):raise Failure('adapter_auth')
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=16384:raise Failure('invalid_input')
    payload=json.loads(self.rfile.read(size));f=asyncio.run_coroutine_threadsafe(broker.dispatch(payload),loop)
    try:out=f.result(timeout=broker.queue_ttl+broker.execution_ttl+broker.validate_ttl+10 if payload['action']=='wait' else 10)
    except concurrent.futures.TimeoutError:f.cancel();raise Failure('timeout')
   except Failure as e:out={'error':e.code}
   except Exception:out={'error':'internal_error'}
   raw=json.dumps(out).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers()
   try:self.wfile.write(raw)
   except OSError:pass
 server=ThreadingHTTPServer(('0.0.0.0',int(os.getenv('ADAPTER_CONTROL_PORT','8082'))),Handler);server.daemon_threads=True
 threading.Thread(target=server.serve_forever,daemon=True).start();return server
