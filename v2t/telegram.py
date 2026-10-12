import json,urllib.request,urllib.error,uuid
from pathlib import Path
from .core import Failure

UPLOAD_LIMIT=50_000_000

def request_error(exc):
    # Do not propagate Telegram descriptions or request URLs containing the token.
    if isinstance(exc,urllib.error.HTTPError):
        if exc.code==403:return 'send_forbidden'
        if exc.code==429:return 'send_rate_limited'
        if exc.code==413:return 'send_too_large'
    return 'send_failed'

class FileBody:
    """Known-length multipart body; no whole-video buffering in manager."""
    def __init__(self,path,filename,field,values,mime):
        self.path=path;self.boundary=uuid.uuid4().hex
        parts=[]
        for key,value in values.items():
            parts.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        assert not any(c in filename for c in '\r\n"/\\')
        parts.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        self.prefix=b''.join(parts);self.suffix=f'\r\n--{self.boundary}--\r\n'.encode()
        self.length=len(self.prefix)+path.stat().st_size+len(self.suffix)
    def __iter__(self):
        yield self.prefix
        with self.path.open('rb') as f:
            while True:
                block=f.read(65536)
                if not block:break
                yield block
        yield self.suffix

class Telegram:
    def __init__(self,token):
        if not token:raise ValueError('TELEGRAM_BOT_TOKEN is required')
        self.base='https://api.telegram.org/bot'+token+'/'
    def call(self,method,values,timeout=45):
        try:
            req=urllib.request.Request(self.base+method,data=json.dumps(values,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=timeout) as r:data=json.loads(r.read(8*1024*1024))
            if not data.get('ok'):raise Failure('send_failed')
            return data['result']
        except Failure:raise
        except Exception as e:raise Failure(request_error(e)) from None
    def send_media(self,chat,path,filename,caption,video=False):
        if path.stat().st_size>UPLOAD_LIMIT:raise Failure('send_too_large')
        field='video' if video else 'document'
        values={'chat_id':str(chat),'caption':caption[:1024]}
        if video:values['supports_streaming']='true'
        mime='video/mp4' if video else 'text/markdown; charset=utf-8' if filename.endswith('.md') else 'application/octet-stream'
        body=FileBody(path,filename,field,values,mime)
        try:
            req=urllib.request.Request(self.base+('sendVideo' if video else 'sendDocument'),data=body,headers={'Content-Type':'multipart/form-data; boundary='+body.boundary,'Content-Length':str(body.length)})
            with urllib.request.urlopen(req,timeout=180) as r:data=json.loads(r.read(1024*1024))
            if not data.get('ok'):raise Failure('send_failed')
            return data['result']['message_id']
        except Failure:raise
        except Exception as e:raise Failure(request_error(e)) from None
    def send_document(self,chat,path:Path,caption):
        return self.send_media(chat,path,path.name,caption)
