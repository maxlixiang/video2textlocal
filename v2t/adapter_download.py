"""Windows-only one-shot child. Keeps validated B Playwright request transport."""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
from .core import Failure,atomic_json,file_hash,read_json
from .douyin_data import _find_video,_video_urls,extract_aweme_id

def media_url(url,config):
 import ipaddress,socket
 from urllib.parse import urlsplit
 p=urlsplit(url);host=(p.hostname or '').lower()
 if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443) or not any(host==d or host.endswith('.'+d) for d in ('douyinvod.com','douyin.com','iesdouyin.com','snssdk.com','bytecdn.cn','zjcdn.com')):raise Failure('download_failed')
 for addr in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
  ip=ipaddress.ip_address(addr[4][0]);fake=ip.version==4 and ip in ipaddress.ip_network('198.18.0.0/15')
  if not ip.is_global and not(fake and config.get('allow_fake_ip_dns')):raise Failure('download_failed')
 return url

def visible_verification(page):
 # Matches B's tolerant captcha reader: a navigation can destroy the old execution context.
 try:return bool(page.evaluate("() => /验证码|完成验证|安全验证|拖动滑块/.test((document.body?.textContent||'').slice(0,8000))"))
 except Exception:return False

def download(job,directory,config):
 from .douyin_parser import DEFAULT_USER_AGENT,_PAGE_DATA
 from playwright.sync_api import sync_playwright
 import importlib.metadata
 expected=job.get('input_id');matched=None;beg=time.monotonic()
 with sync_playwright() as pw:
  browser=pw.chromium.launch(channel='chromium',headless=True,timeout=15000)
  context=browser.new_context(user_agent=DEFAULT_USER_AGENT,locale='zh-CN',timezone_id='Asia/Shanghai',viewport={'width':1440,'height':900})
  page=context.new_page();candidates=[]
  def route(r):
   if r.request.resource_type in ('image','media','font'):r.abort()
   else:r.continue_()
  context.route('**/*',route)
  def finished(q):
   try:
    r=q.response()
    if not r or q.method=='OPTIONS':return
    path=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(q.url).path
    if '/aweme/' not in path and '/iteminfo' not in path:return
    data=json.loads(r.body());target=expected or extract_aweme_id(page.url)
    if target:
     item=_find_video(data,target)
     if item:candidates.append(item)
   except Exception:pass
  page.on('requestfinished',finished)
  try:
   if context.cookies():raise Failure('invalid_artifact')
   try:page.goto(job['url'],wait_until='commit',timeout=15000)
   except Exception:pass
   end=time.monotonic()+60;next_read=0
   while time.monotonic()<end:
    expected=expected or extract_aweme_id(page.url)
    if visible_verification(page):raise Failure('verification_required')
    if candidates:matched=candidates[0];break
    if expected and time.monotonic()>=next_read:
     try:matched=_find_video(page.evaluate(_PAGE_DATA,expected).get('item'),expected)
     except Exception:pass
     if matched:break
     next_read=time.monotonic()+5
    page.wait_for_timeout(250)
   if not matched:raise Failure('douyin_empty_response')
   matched_id=str(matched.get('aweme_id') or matched.get('awemeId') or matched.get('item_id'))
   if matched_id!=expected:raise Failure('target_mismatch')
   urls=_video_urls(matched)
   if not urls:raise Failure('no_media')
   url=urls[0]
   for redirect in range(4):
    from urllib.parse import urlsplit
    atomic_json(directory/'download-stage.json',{'stage':'media_request','scheme':urlsplit(url).scheme,'host':urlsplit(url).hostname,'redirect':redirect})
    response=context.request.get(media_url(url,config),headers={'User-Agent':DEFAULT_USER_AGENT,'Referer':page.url},timeout=45000,max_redirects=0)
    if response.status not in (301,302,303,307,308):break
    from urllib.parse import urljoin
    url=urljoin(url,response.headers.get('location',''))
   else:raise Failure('download_failed')
   if not response.ok:raise Failure('download_failed')
   declared=int(response.headers.get('content-length','0'))
   if declared>config.get('max_bytes',524288000):raise Failure('too_large')
   # APIRequestContext holds Node's full response; parent Job Object is the actual safety limit.
   body=response.body()
   if not 2048<len(body)<=config.get('max_bytes',524288000):raise Failure('too_large')
   path=directory/'media.part';path.write_bytes(body)
   metadata={'title':str(matched.get('desc') or '')[:500],'matched_id':matched_id,'resolved_id':extract_aweme_id(page.url),'windows':{'browser':browser.version,'playwright':importlib.metadata.version('playwright'),'cookie_count':len(context.cookies()),'elapsed_s':time.monotonic()-beg,'fixture':False,'declared_bytes':declared}}
   return path,metadata
  finally:context.close();browser.close()

def validate(path,config,want_video=False):
 try:
  r=subprocess.run([config['ffprobe'],'-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,timeout=30,check=True)
  info=json.loads(r.stdout);duration=float(info['format']['duration'])
  has_audio=any(s['codec_type']=='audio' for s in info['streams']);has_video=any(s['codec_type']=='video' for s in info['streams'])
  if not has_audio and not(want_video and has_video):raise Failure('no_media')
  if want_video and not has_video:raise Failure('no_video')
  if not 0<duration<=config.get('max_seconds',7200):raise Failure('too_long')
  subprocess.run([config['ffmpeg'],'-nostdin','-v','error','-xerror','-i',str(path),'-map','0:a:0' if has_audio else '0:v:0','-f','null','NUL'],capture_output=True,timeout=180,check=True)
  return {'duration':duration,'has_audio':has_audio,'has_video':has_video,'full_audio_decode':has_audio,'full_video_decode':not has_audio}
 except Failure:raise
 except Exception:raise Failure('no_media') from None

def main():
 p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--config',required=True);a=p.parse_args();d=Path(a.directory)
 # Do not launch Node/Chromium before kernel process-tree budget is attached by parent.
 until=time.monotonic()+10
 while not (d/'budget-ready').exists():
  if time.monotonic()>until:return 1
  time.sleep(.05)
 config=read_json(Path(a.config));job=read_json(d/'job.json')
 try:
  if config.get('test_allocate_mib'):
   atomic_json(d/'allocation-requested.json',{'bytes':config['test_allocate_mib']*1024**2})
   value=bytearray(config['test_allocate_mib']*1024**2);atomic_json(d/'allocation-succeeded.json',{'succeeded':True});time.sleep(2)
  if config.get('fixture_path'):
   path=d/'media.part';shutil.copyfile(config['fixture_path'],path);meta={'matched_id':job['input_id'] or '7692261748124177640','resolved_id':job['input_id'] or '7692261748124177640','windows':{'fixture':True}}
  else:path,meta=download(job,d,config)
  meta['windows']['decode']=validate(path,config,job.get('mode')=='video');path.replace(d/'media.complete');meta.update(bytes=(d/'media.complete').stat().st_size,sha256=file_hash(d/'media.complete'))
  atomic_json(d/'download.json',meta);return 0
 except MemoryError:atomic_json(d/'download.json',{'error':'adapter_memory_limit'});return 1
 except Failure as e:atomic_json(d/'download.json',{'error':e.code,'exception_type':'Failure'});return 1
 except Exception as e:
  import traceback
  frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(e.__traceback__)][-5:]
  atomic_json(d/'download.json',{'error':'timeout' if type(e).__name__=='TimeoutError' else 'download_failed','exception_type':type(e).__name__,'frames':frames});return 1
if __name__=='__main__':raise SystemExit(main())
