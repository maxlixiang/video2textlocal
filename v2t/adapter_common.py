"""Small adapter protocol primitives. No browser/ASR import, no credential logging."""
import hashlib,hmac,json,os,re,shutil,ssl,time,urllib.error,urllib.request
from pathlib import Path
from .core import Failure,atomic_json,read_json

def enabled():return os.getenv('WINDOWS_ADAPTER_ENABLED','0')=='1'
def key():return Path(os.environ['ADAPTER_INTERNAL_KEY_FILE']).read_text().strip()
def ident(value):
 if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise Failure('invalid_input')
 return value

def control(action,payload):
 data=json.dumps({'action':action,**payload}).encode()
 req=urllib.request.Request(os.getenv('ADAPTER_CONTROL_URL','http://manager:8082'),data=data,headers={'Content-Type':'application/json','X-Adapter-Key':key()})
 try:
  with urllib.request.urlopen(req,timeout=10) as r:out=json.load(r)
 except Exception:raise Failure('service_unavailable') from None
 if out.get('error'):raise Failure(out['error'])
 return out

def usage(root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 total=0
 for p in root.rglob('*'):
  try:
   if p.is_file() and not p.is_symlink():total+=p.stat().st_size
  except OSError:pass
 return total

def space(root,reserve,quota,minimum,other_reserved=0):
 used=usage(root);free=shutil.disk_usage(root).free
 if used+reserve+other_reserved>quota:raise Failure('adapter_quota')
 if free-reserve-other_reserved<minimum:raise Failure('disk_full')
 return {'used_bytes':used,'free_bytes':free,'reserved_bytes':reserve+other_reserved}

def cert_remaining(path):
 try:d=ssl._ssl._test_decode_cert(str(path));return ssl.cert_time_to_seconds(d['notAfter'])-time.time()
 except Exception:raise Failure('adapter_auth') from None

class Client:
 def __init__(self,config):self.config=config
 def call(self,route,payload=None,body=None,headers=None):
  c=self.config
  ctx=ssl.create_default_context(cafile=c['ca']);ctx.load_cert_chain(c['cert'],c['key'])
  data=body if body is not None else json.dumps(payload or {}).encode()
  req=urllib.request.Request(c['endpoint'].rstrip('/')+route,data=data,headers={'Content-Type':'application/octet-stream' if body is not None else 'application/json',**(headers or {})})
  try:
   # Dedicated loopback channel never uses global/environment proxies.
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
   with opener.open(req,timeout=15) as r:out=json.load(r)
  except urllib.error.HTTPError as e:
   try:out=json.load(e)
   except Exception:raise Failure('adapter_auth') from None
  except Exception:raise Failure('adapter_auth') from None
  if out.get('error'):raise Failure(out['error'])
  return out
