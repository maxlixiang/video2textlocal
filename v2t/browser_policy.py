"""Anonymous browser egress policy, shared across navigations and all subresources."""
import ipaddress,socket
from urllib.parse import urlsplit
from .core import Failure
from .net import TRUSTED_DNS_DOMAINS
DOMAINS=TRUSTED_DNS_DOMAINS+('zjcdn.com','douyinvod.com','amemv.com','bytegecko.com','bytedance.net')

def browser_url(url,allow_fake=False,resolver=socket.getaddrinfo):
 p=urlsplit(url)
 if p.scheme in ('about','data','blob'):return url
 if p.scheme not in ('http','https','ws','wss') or p.username or p.password or p.port not in (None,80,443) or not p.hostname:raise Failure('download_failed')
 host=p.hostname.lower()
 if not any(host==d or host.endswith('.'+d) for d in DOMAINS):raise Failure('download_failed')
 try:answers=resolver(host,p.port or (443 if p.scheme in ('https','wss') else 80),type=socket.SOCK_STREAM)
 except OSError:raise Failure('network_error') from None
 if not answers:raise Failure('network_error')
 for row in answers:
  ip=ipaddress.ip_address(row[4][0]);fake=ip.version==4 and ip in ipaddress.ip_network('198.18.0.0/15')
  if not ip.is_global and not(fake and allow_fake):raise Failure('download_failed')
 return url

def install_browser_policy(context,allow_fake=False,resolver=socket.getaddrinfo):
 def route(r):
  try:
   browser_url(r.request.url,allow_fake,resolver)
   if r.request.resource_type in ('image','media','font'):r.abort();return
   response=r.fetch(max_redirects=0,timeout=15000)
   if response.status in (301,302,303,307,308):
    from urllib.parse import urljoin
    browser_url(urljoin(r.request.url,response.headers.get('location','')),allow_fake,resolver)
   r.fulfill(response=response)
  except Exception:r.abort()
 context.route('**/*',route)
 def websocket_route(ws):
  try:browser_url(ws.url,allow_fake,resolver);ws.connect_to_server()
  except Exception:ws.close()
 context.route_web_socket('**/*',websocket_route)
