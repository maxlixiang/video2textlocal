"""Manual foreground Windows worker. TLS/heartbeat parent, budgeted browser child."""
import argparse,json,os,subprocess,sys,threading,time
from pathlib import Path
from .adapter_common import Client,space,cert_remaining
from .core import Failure,atomic_json,file_hash,read_json
from .adapter_memory import Budget

class Worker:
 def __init__(self,path):
  self.path=Path(path);self.config=read_json(self.path);self.client=Client(self.config);self.root=Path(self.config['spool']);self.root.mkdir(parents=True,exist_ok=True)
  self.quota=self.config.get('quota_bytes',4*1024**3);self.minimum=self.config.get('min_free_bytes',2*1024**3)
 def execute(self,job):
  p={k:job[k] for k in ('task_id','generation')};stop=threading.Event();failure=[];beats=[]
  ownership={'server':False};last_ok=[time.monotonic()]
  def heartbeat():
   while not stop.wait(self.config.get('heartbeat_seconds',15)):
    try:
     r=self.client.call('/v1/heartbeat',p);last_ok[0]=time.monotonic();ownership['server']=r['state'] in ('validating','complete');beats.append({'time':time.time(),'state':r['state']})
     if r['state']=='complete':return
    except Failure as e:
     if e.code in ('adapter_lease_expired','adapter_auth','adapter_certificate'):failure.append(e.code);return
     # Transport failure is retriable only while lease's known window has not expired.
     beats.append({'time':time.time(),'error':e.code})
     if not ownership['server'] and time.monotonic()-last_ok[0]>self.config.get('lease_seconds',45):failure.append('adapter_lease_expired');return
  thread=threading.Thread(target=heartbeat,daemon=True);thread.start();jobdir=self.root/job['task_id'];jobdir.mkdir(exist_ok=True)
  journal=read_json(jobdir/'journal.json',{});meta=None
  try:
   status=self.client.call('/v1/status',p)
   if status['state'] in ('validating','complete'):
    while status['state']!='complete':
     time.sleep(.5);status=self.client.call('/v1/status',p)
    journal.update(state='complete',heartbeats=beats);atomic_json(jobdir/'journal.json',journal);return status
   complete=jobdir/'media.complete'
   if complete.exists() and journal.get('url_hash')==__import__('hashlib').sha256(job['url'].encode()).hexdigest() and journal.get('sha256')==file_hash(complete):meta=journal['meta']
   if meta is None:
    space(self.root,self.config.get('max_bytes',524288000)+256*1024**2,self.quota,self.minimum)
    atomic_json(jobdir/'job.json',job)
    gate=jobdir/'budget-ready'
    # One explicit known file deletion; prevents reusing an old gate before budget attachment.
    if gate.exists():gate.unlink()
    childenv={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','HOMEDRIVE','HOMEPATH')}
    temp=jobdir/'browser-temp';temp.mkdir(exist_ok=True);childenv.update(TEMP=str(temp),TMP=str(temp),PYTHONDONTWRITEBYTECODE='1')
    childconfig={k:v for k,v in self.config.items() if k not in ('cert','key','ca','endpoint','credential_manifest')}
    atomic_json(jobdir/'child-config.json',childconfig)
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parent.parent/'windows_download.py'),'--directory',str(jobdir),'--config',str(jobdir/'child-config.json')],env=childenv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    budget=Budget(child,self.config.get('memory_budget_bytes',2*1024**3));gate.touch()
    started=time.time();metrics={}
    try:
     while child.poll() is None:
      metrics=budget.metrics()
      if failure or time.time()>job['execution_deadline']:budget.terminate();failure.append('adapter_lease_expired');break
      try:space(self.root,0,self.quota,self.minimum)
      except Failure as e:budget.terminate();failure.append(e.code);break
      time.sleep(.2)
     child.wait(timeout=10);metrics=budget.metrics()
    finally:budget.close()
    journal['memory']=metrics
    meta=read_json(jobdir/'download.json',{})
    if failure:raise Failure(failure[0])
    if meta.get('error'):raise Failure(meta['error'])
    if child.returncode or not complete.exists():raise Failure('adapter_memory_limit' if metrics.get('peak_private_commit_bytes',0)>.8*self.config.get('memory_budget_bytes',2*1024**3) else 'download_failed')
    meta['windows']['memory']=metrics
    journal={'url_hash':__import__('hashlib').sha256(job['url'].encode()).hexdigest(),'sha256':meta['sha256'],'meta':meta,'generation':job['generation'],'state':'downloaded','heartbeats':beats}
    atomic_json(jobdir/'journal.json',journal)
   jobstate=self.client.call('/v1/status',p)
   if jobstate['state']=='complete':return jobstate
   if jobstate['state'] not in ('validating',):
    start=self.client.call('/v1/start',{**p,**meta});offset=start['offset']
    with complete.open('rb') as f:
     while offset<meta['bytes']:
      if failure:raise Failure(failure[0])
      f.seek(offset);block=f.read(4*1024**2)
      headers={'X-Task':p['task_id'],'X-Generation':p['generation'],'X-Offset':str(offset),'X-Chunk-Sha256':__import__('hashlib').sha256(block).hexdigest()}
      value=None
      for retry in range(3):
       try:value=self.client.call('/v1/chunk',body=block,headers=headers);break
       except Failure as e:
        if e.code not in ('adapter_network','service_unavailable'):raise
        if retry==2:raise
        time.sleep(retry+1)
      offset=value['offset'];journal.update(state='uploading',offset=offset,generation=job['generation']);atomic_json(jobdir/'journal.json',journal)
      if self.config.get('test_pause_after_chunks'):time.sleep(self.config['test_pause_after_chunks'])
    self.client.call('/v1/finalize',p);ownership['server']=True
   while True:
    result=self.client.call('/v1/status',p)
    if result['state']=='complete':journal.update(state='complete',heartbeats=beats);atomic_json(jobdir/'journal.json',journal);return result
    if failure:raise Failure(failure[0])
    time.sleep(.5)
  except Failure as e:
   journal.update(error=e.code,state='suspended' if e.code in ('adapter_network','service_unavailable') else 'failed',heartbeats=beats);atomic_json(jobdir/'journal.json',journal)
   if e.code not in ('adapter_network','service_unavailable'):
    try:self.client.call('/v1/failure',{**p,'code':e.code})
    except Failure:pass
   raise
  finally:stop.set();thread.join(timeout=16)
 def run(self,max_jobs=0):
  done=0;backoff=1;warned_certificate=None
  while not max_jobs or done<max_jobs:
   certificate=self.client.credentials()['cert'];remaining=cert_remaining(certificate)
   if remaining<86400 and warned_certificate!=certificate:
    print('adapter_certificate_expires_within_24_hours',flush=True);warned_certificate=certificate
   if remaining<self.config.get('certificate_claim_margin_seconds',900):
    print('adapter_certificate_renewal_required',flush=True);return 1
   try:job=self.client.call('/v1/claim',{});backoff=1
   except Failure as e:
    if e.code not in ('adapter_network','service_unavailable'):
     print(e.code,flush=True);return 1
    print('adapter_reconnecting:'+str(backoff),flush=True)
    time.sleep(backoff);backoff=min(backoff*2,self.config.get('reconnect_max_seconds',30));continue
   if job.get('idle'):time.sleep(1);continue
   try:
    result=self.execute(job);print(json.dumps({'task_id':job['task_id'],'state':result['state']},ensure_ascii=False),flush=True);done+=1
   except Failure as e:
    print(json.dumps({'task_id':job['task_id'],'error':e.code}),flush=True)
    if e.code in ('adapter_network','service_unavailable'):
     # Keep journal and ask broker for the same still-valid lease after reconnecting.
     time.sleep(backoff);backoff=min(backoff*2,30);continue
    if e.code in ('adapter_auth','adapter_certificate'):return 1
    done+=1
  return 0

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--max-jobs',type=int,default=0);a=p.parse_args()
 if os.name!='nt':raise SystemExit('Windows foreground worker required')
 worker=Worker(a.config)
 import msvcrt
 singleton=(worker.root/'worker.lock').open('a+b');singleton.seek(0);singleton.write(b'0');singleton.flush();singleton.seek(0)
 try:msvcrt.locking(singleton.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:raise SystemExit('worker already owns spool') from None
 try:return worker.run(a.max_jobs)
 except Failure as e:print(e.code,flush=True);return 1
if __name__=='__main__':raise SystemExit(main())
