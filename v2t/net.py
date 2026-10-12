"""Errors never include remote URLs, response bodies, tokens or headers."""
import ipaddress
import json
import socket
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .core import Failure

FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")
TRUSTED_DNS_DOMAINS = ("douyin.com", "iesdouyin.com", "douyinvod.com", "douyincdn.com", "byteimg.com", "bytecdn.cn",
                       "pstatp.com", "snssdk.com", "bytedance.com", "ibytedtos.com", "bytegecko.com", "ttwstatic.com",
                       "fxtwitter.com", "video.twimg.com", "isv-data.oss-cn-hangzhou.aliyuncs.com")
TRUSTED_DNS_DOMAINS += ("douyinstatic.com", "bytescm.com", "bytegoofy.com", "bytetos.com", "yhgfb-cn-static.com")
TRUSTED_DNS_DOMAINS += ("zijieapi.com", "applogcdn.com", "ibytedapm.com", "bytednsdoc.com", "byteeffecttos.com", "feelgood.cn", "bytetcc.com")


def public_url(url):
    p = urlsplit(url)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise Failure("download_failed")
    try:
        answers = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
        trusted_host = any(p.hostname == d or p.hostname.endswith("." + d) for d in TRUSTED_DNS_DOMAINS)
        def accepted(address):
            ip = ipaddress.ip_address(address)
            return ip.is_global or (os.getenv("ALLOW_FAKE_IP_DNS") == "1" and trusted_host and ip.version == 4 and ip in FAKE_IP_RANGE)
        if not answers or any(not accepted(a[4][0]) for a in answers):
            raise Failure("download_failed")
    except OSError:
        raise Failure("download_failed") from None
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlsplit(req.full_url).hostname != urlsplit(newurl).hostname:
            redirected.remove_header("Cookie")
            redirected.remove_header("Authorization")
        return redirected


def connection_error(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (socket.gaierror, ConnectionError, TimeoutError))


def open_public(url, timeout=45, headers=None):
    try:
        return urllib.request.build_opener(SafeRedirect()).open(
            urllib.request.Request(public_url(url), headers=headers or {}), timeout=timeout)
    except Failure:
        raise
    except Exception as exc:
        raise Failure("network_error" if connection_error(exc) else "download_failed") from None


def json_request(url, payload=None, timeout=60, headers=None, error="service_unavailable"):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            result = json.loads(r.read(8 * 1024 * 1024))
        if isinstance(result, dict) and result.get("error"):
            raise Failure(result["error"])
        return result
    except Failure:
        raise
    except urllib.error.HTTPError as exc:
        if error == "polish_failed":
            code = "deepseek_auth" if exc.code in {401, 403} else "deepseek_rate_limited" if exc.code == 429 else "deepseek_config" if exc.code in {400, 404, 422} else error
            raise Failure(code) from None
        raise Failure(error) from None
    except Exception:
        raise Failure(error) from None
