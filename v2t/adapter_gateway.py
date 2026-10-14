"""mTLS gateway in download service; filesystem receipts, never SQLite."""
import hashlib,json,os,ssl,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .adapter_common import control,ident,space,cert_remaining
from .core import Failure,atomic_json,file_hash,read_json
from .download import probe,decode_audio,probe_info

class Gateway:
 def __init__(self):
  self.root=Path(os.getenv('MEDIA_ROOT','/media'));self.root.mkdir(parents=True,exist_ok=True)
  self.lock=threading.RLock();self.running=set();self.stop=threading.Event()
  self.quota=int(os.getenv('ADAPTER_LINUX_QUOTA_BYTES',str(8*1024**3)));self.minimum=int(os.getenv('ADAPTER_MIN_FREE_BYTES',str(2*1024**3)))
  threading.Thread(target=self.recover,daemon=True).start()
 def directory(self,p):return self.root/ident(p['task_id'])/'adapter'/ident(p['generation'])
 def payload(self,r):return {k:r[k] for k in ('task_id','generation','worker')}
 def recover(self):
  while not self.stop.wait(2):
   for path in self.root.glob('*/adapter/*/receipt.json'):
    r=read_json(path,{})
    if r.get('state') in ('received','validating','complete'):
     self.spawn(path.parent)
 def spawn(self,d):
  with self.lock:
   if str(d) in self.running:return
   self.running.add(str(d))
  threading.Thread(target=self.validate,args=(d,),daemon=True).start()
 def validate(self,d):
  try:
   r=read_json(d/'receipt.json');p=self.payload(r)
   if r['state']=='complete':
    control('finish',{**p,'completed_at':r['completed_at'],'receipt':r['media']});r['state']='acknowledged';atomic_json(d/'receipt.json',r);return
   job=control('accept',p)
   r['state']='validating';atomic_json(d/'receipt.json',r)
   delay=float(os.getenv('ADAPTER_TEST_DECODE_DELAY','0')) if os.getenv('ADAPTER_TEST_MODE')=='1' else 0
   if delay:time.sleep(delay)
   destination=self.root/r['task_id'];source=d/'media.part'
   # Existing final files can recover a rename/metadata crash, but only with this verified receipt.
   final=destination/'media.bin';audio=destination/'audio.wav'
   source=source if source.exists() else final
   if file_hash(source)!=r['sha256']:raise Failure('invalid_artifact')
   properties=probe_info(source);want_video=job.get('mode')=='video'
   if want_video and not properties['has_video']:raise Failure('no_video')
   duration=probe(source,require_audio=not want_video);temporary=d/'audio.part.wav'
   if time.time()>job['validation_deadline']:raise Failure('timeout')
   import subprocess
   try:
    subprocess.run(["ffmpeg","-nostdin","-y","-v","error","-xerror","-i",str(source),*( ["-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(temporary)] if properties["has_audio"] else ["-map","0:v:0","-f","null","-"] )],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=max(1,job["validation_deadline"]-time.time()),check=True)
   except subprocess.TimeoutExpired:raise Failure("timeout") from None
   except Exception:raise Failure("no_media") from None
   if time.time()>job['validation_deadline']:raise Failure('timeout')
   if source!=final:source.replace(final)
   if properties["has_audio"]:temporary.replace(audio)
   meta={'sha256':file_hash(final),'audio_sha256':file_hash(audio) if properties['has_audio'] else None,'bytes':final.stat().st_size,'duration':duration,'media_id':r['matched_id'],'platform':'douyin','title':r.get('title',''),**properties,'validation':'windows_handoff+ffprobe+full_ffmpeg_decode','adapter_generation':r['generation'],'windows':r.get('windows',{})}
   atomic_json(destination/'media.json',meta)
   r.update(state='complete',media=meta,completed_at=time.time());atomic_json(d/'receipt.json',r)
   control('finish',{**p,'completed_at':r['completed_at'],'receipt':meta});r['state']='acknowledged';atomic_json(d/'receipt.json',r)
  except Failure as e:
   if e.code=='service_unavailable':return
   if 'r' in locals() and r.get('state')=='complete':return
   if 'r' in locals():
    r['state']='failed';r['error']=e.code;atomic_json(d/'receipt.json',r)
    try:control('failure',{**self.payload(r),'code':e.code})
    except Failure:pass
  except Exception:
   if 'r' in locals():r['state']='failed';r['error']='invalid_artifact';atomic_json(d/'receipt.json',r)
  finally:
   with self.lock:self.running.discard(str(d))
 def operation(self,action,p,data=None):
  if action in ('claim','heartbeat','status','failure','retention','retention_check'):return control(action,p)
  if action in ('test_submit','test_retry'):
   if os.getenv('ADAPTER_TEST_MODE')!='1':raise Failure('invalid_input')
   return control(action,p)
  if action=='start':
   if p.get('windows',{}).get('fixture') and os.getenv('ADAPTER_TEST_MODE')!='1':raise Failure('invalid_artifact')
   job=control('check',p);d=self.directory(p)
   if not isinstance(p.get('bytes'),int) or not 2048<=p['bytes']<=int(os.getenv('MAX_MEDIA_BYTES','524288000')):raise Failure('too_large')
   if not isinstance(p.get('sha256'),str) or len(p['sha256'])!=64:raise Failure('invalid_input')
   if not isinstance(p.get('matched_id'),str) or not p['matched_id'].isdigit():raise Failure('target_mismatch')
   if job['input_id'] and job['input_id']!=p['matched_id']:raise Failure('target_mismatch')
   if p.get('resolved_id')!=p['matched_id']:raise Failure('target_mismatch')
   with self.lock:
    old=read_json(d/'receipt.json')
    if old:
     if old['sha256']!=p['sha256'] or old['bytes']!=p['bytes']:raise Failure('invalid_artifact')
     return {'offset':old['offset'],'state':old['state']}
    reserved=0
    for f in self.root.glob('*/adapter/*/receipt.json'):
     r=read_json(f,{})
     if r.get('state')=='uploading':reserved+=max(0,r['bytes']-r['offset'])+int(os.getenv('MAX_MEDIA_SECONDS','7200'))*32000
    reserve=p['bytes']+int(os.getenv('MAX_MEDIA_SECONDS','7200'))*32000
    budget=space(self.root,reserve,self.quota,self.minimum,reserved)
    control('start',p);d.mkdir(parents=True,exist_ok=False)
    win={k:v for k,v in p.get('windows',{}).items() if k in ('browser','playwright','cookie_count','elapsed_s','memory','fixture','decode','cleanup_errors')}
    r={**self.payload(p),'bytes':p['bytes'],'sha256':p['sha256'],'matched_id':p['matched_id'],'resolved_id':p['resolved_id'],'state':'uploading','offset':0,'windows':win,'title':str(p.get('title') or '')[:500],'disk_admission':budget}
    (d/'media.part').touch();atomic_json(d/'receipt.json',r);return {'offset':0,'state':'uploading'}
  if action=='upload_status':
   control('status',p);r=read_json(self.directory(p)/'receipt.json')
   if not r:raise Failure('invalid_input')
   return {'offset':r['offset'],'state':r['state']}
  if action=='chunk':
   control('check',p);d=self.directory(p)
   with self.lock:
    r=read_json(d/'receipt.json');offset=int(p['offset']);data=data or b''
    if not r or not 0<len(data)<=4*1024**2 or offset<0 or offset+len(data)>r['bytes']:raise Failure('adapter_offset')
    if hashlib.sha256(data).hexdigest()!=p['chunk_hash']:raise Failure('adapter_offset')
    part=d/'media.part'
    if offset<r['offset']:
     with part.open('rb') as f:f.seek(offset);old=f.read(len(data))
     if old!=data:raise Failure('adapter_offset')
     return {'offset':r['offset'],'duplicate':True}
    if offset!=r['offset']:raise Failure('adapter_offset')
    # Physical append before manifest is recoverable by retransmitting and truncating only this file.
    space(self.root,len(data),self.quota,self.minimum)
    with part.open('r+b') as f:f.seek(offset);f.write(data);f.truncate(offset+len(data));f.flush();os.fsync(f.fileno())
    r['offset']+=len(data);atomic_json(d/'receipt.json',r);return {'offset':r['offset']}
  if action=='finalize':
   control('status',p);d=self.directory(p)
   with self.lock:
    r=read_json(d/'receipt.json')
    if not r:raise Failure('invalid_input')
    if r['state'] in ('received','validating','complete','acknowledged'):return {'state':r['state'],'duplicate':True}
    if r['offset']!=r['bytes'] or file_hash(d/'media.part')!=r['sha256']:raise Failure('invalid_artifact')
    # Receipt first; if broker acceptance or this process crashes, recovery can repeat acceptance.
    r['state']='received';atomic_json(d/'receipt.json',r);control('accept',p)
   self.spawn(d);return {'state':'validating'}
  raise Failure('invalid_input')

def start_gateway():
 gateway=Gateway()
 class Server(ThreadingHTTPServer):
  daemon_threads=True
  def get_request(self):
   sock,addr=super().get_request();sock.settimeout(15)
   try:
    cert=Path(os.environ['ADAPTER_SERVER_CERT']);directory=cert.parent.resolve();cert=directory/cert.name;priv=directory/Path(os.environ['ADAPTER_SERVER_KEY']).name
    if cert_remaining(cert)<=0:print('adapter_server_certificate_expired',flush=True)
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(cert,priv);ctx.load_verify_locations(os.environ['ADAPTER_CA_FILE']);ctx.verify_mode=ssl.CERT_REQUIRED
    return ctx.wrap_socket(sock,server_side=True),addr
   except Exception:sock.close();raise OSError('adapter_auth') from None
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_POST(self):
   status=200
   try:
    fp=hashlib.sha256(self.connection.getpeercert(binary_form=True)).hexdigest()
    identities=read_json(Path(os.environ['ADAPTER_WORKERS_FILE']),{});worker=identities.get(fp)
    if not worker:raise Failure('adapter_auth')
    size=int(self.headers.get('Content-Length','0'));action=self.path.removeprefix('/v1/')
    if action=='chunk':
     if not 0<size<=4*1024**2:raise Failure('too_large')
     data=self.rfile.read(size);p={'task_id':self.headers['X-Task'],'generation':self.headers['X-Generation'],'offset':int(self.headers['X-Offset']),'chunk_hash':self.headers['X-Chunk-Sha256'],'worker':worker}
     out=gateway.operation(action,p,data)
    else:
     if not 0<size<=16384:raise Failure('invalid_input')
     p=json.loads(self.rfile.read(size));p['worker']=worker;out=gateway.operation(action,p)
   except Failure as e:out={'error':e.code};status=403 if e.code=='adapter_auth' else 409
   except Exception:out={'error':'internal_error'};status=500
   raw=json.dumps(out,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers()
   try:self.wfile.write(raw)
   except OSError:pass
 server=Server(('0.0.0.0',int(os.getenv('ADAPTER_GATEWAY_PORT','8443'))),Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start();return server
