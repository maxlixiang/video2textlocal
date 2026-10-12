"""Parser adapted from maxlixiang/Telegram-Media-AI-Bot at 92b869be0569eaf0cdd4fd17f2a2081a6484deef.
Uses full Chromium, target ID matching, requestfinished body reads and page-data fallback.
No historical state, login or verification bypass. Outer timeout and diagnostics added by this project.
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from urllib.parse import parse_qs,urlparse
from playwright.async_api import Error as BrowserError,TimeoutError as BrowserTimeout,async_playwright
from .core import Failure,atomic_json
from .douyin_data import extract_aweme_id,_video_urls,_find_video
logger=logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
logger.propagate = False
class DouyinDownloadError(RuntimeError):
    pass

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'



_PAGE_DATA = '(awemeId) => {\n    let visits = 0;\n    const seen = new WeakSet();\n    function find(value) {\n        if (!value || typeof value !== \'object\' || seen.has(value) || ++visits > 20000) return null;\n        seen.add(value);\n        const id = value.aweme_id || value.awemeId || value.item_id;\n        if (String(id) === awemeId && value.video) return value;\n        for (const child of Object.values(value)) {\n            const found = find(child);\n            if (found) return found;\n        }\n        return null;\n    }\n    let item = find(window._ROUTER_DATA) || find(window.RENDER_DATA);\n    if (!item) {\n        for (const script of document.querySelectorAll(\'script[type="application/json"], script#RENDER_DATA, script#__NEXT_DATA__\')) {\n            let data;\n            try { data = JSON.parse(script.textContent); }\n            catch (_) { try { data = JSON.parse(decodeURIComponent(script.textContent)); } catch (_) {} }\n            item = find(data);\n            if (item) break;\n        }\n    }\n    const text = (document.body?.textContent || \'\').slice(0, 5000);\n    return {\n        item, ready_state: document.readyState,\n        captcha: /验证码|完成验证|安全验证|拖动滑块/.test(text),\n        video_loading: text.includes(\'视频数据加载中\')\n    };\n}'

def _safe_location(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.hostname or 'unknown'}{parsed.path}"

def _is_douyin_host(url: str) -> bool:
    host = (urlparse(url).hostname or '').lower()
    return any((host == domain or host.endswith('.' + domain) for domain in ('douyin.com', 'iesdouyin.com')))

def _is_video_request(url: str) -> bool:
    path = urlparse(url).path.lower()
    return _is_douyin_host(url) and any((key in path for key in ('/aweme/detail', '/aweme/v1/web/aweme/detail', '/aweme/v1/web/feed', '/iteminfo')))

async def _read_page_data(page, aweme_id: str, stats: dict):
    try:
        snapshot = await asyncio.wait_for(page.evaluate(_PAGE_DATA, aweme_id), timeout=2)
        for key in ('ready_state', 'captcha', 'video_loading'):
            stats[key] = snapshot.get(key)
        return _find_video(snapshot.get('item'), aweme_id)
    except (asyncio.TimeoutError, BrowserTimeout):
        stats['page_read_timeouts'] += 1
    except BrowserError:
        stats['page_read_errors'] += 1
    return None

async def _parse_douyin_page(context, url: str, stats: dict):
    started = time.monotonic()
    page = await context.new_page()
    payloads = deque(maxlen=8)
    tasks = set()
    pending_responses = {}
    matched = None
    aweme_id = extract_aweme_id(url)

    async def route_request(route):
        if route.request.resource_type in {'image', 'media', 'font'}:
            stats['blocked_resources'] += 1
            await route.abort()
        else:
            from .net import public_url
            try:
                await asyncio.to_thread(public_url, route.request.url)
                await route.continue_()
            except Failure:
                blocked = stats.setdefault('blocked_request_hosts', [])
                host = urlparse(route.request.url).hostname
                if host and host not in blocked:
                    blocked.append(host)
                await route.abort()

    def on_request(request):
        if _is_video_request(request.url):
            stats['video_requests'] += 1
            logger.info('抖音视频请求 endpoint=%s', _safe_location(request.url))

    def on_request_failed(request):
        pending_responses.pop(request, None)
        if request.resource_type in {'image', 'media', 'font'}:
            return
        stats['request_failures'] += 1
        if request.resource_type == 'script':
            stats['script_request_failures'] += 1
        if (urlparse(request.url).hostname or '') == 'invalid':
            stats['invalid_requests'] += 1
        if _is_video_request(request.url):
            stats['video_request_failures'] += 1
        if _is_video_request(request.url) or (request.resource_type == 'script' and stats['script_request_failures'] <= 10) or (stats['request_failures'] <= 10 and stats['invalid_requests'] <= 2):
            failure = request.failure or 'unknown'
            code = failure if failure.startswith('net::') and ' ' not in failure else 'REQUEST_FAILED'
            logger.warning('抖音请求失败 resource=%s endpoint=%s error=%s', request.resource_type, _safe_location(request.url), code)

    def on_page_error(error):
        stats['script_errors'] += 1
        logger.warning('抖音页面脚本异常 error_type=%s', error.name)

    async def read_response(response):
        nonlocal matched
        is_video = _is_video_request(response.url)
        try:
            body = await asyncio.wait_for(response.body(), timeout=10 if is_video else 3)
            if is_video:
                stats['video_body_bytes'] = len(body)
                logger.info('抖音视频响应内容 endpoint=%s bytes=%s', _safe_location(response.url), len(body))
                if not body.strip():
                    stats['video_empty_responses'] += 1
                    return
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):
                stats['json_read_errors'] += 1
                if is_video:
                    stats['video_non_json_responses'] += 1
                    logger.warning('抖音视频响应不是 JSON endpoint=%s bytes=%s', _safe_location(response.url), len(body))
                return
            stats['json_responses'] += 1
            if is_video:
                stats['video_json_responses'] += 1
            if is_video and isinstance(data, dict):
                api_status = data.get('status_code')
                if isinstance(api_status, int) and (not isinstance(api_status, bool)):
                    stats['video_api_status'] = api_status
            target = aweme_id or extract_aweme_id(page.url)
            if target:
                item = _find_video(data, target)
                if item:
                    matched = item
            else:
                payloads.append(data)
        except asyncio.TimeoutError:
            stats['json_read_errors'] += 1
            if is_video:
                stats['video_body_read_timeouts'] += 1
        except BrowserError:
            stats['json_read_errors'] += 1
            if is_video:
                stats['video_body_read_errors'] += 1

    def on_response(response):
        if response.request.resource_type == 'script' and response.status >= 400:
            stats['script_http_errors'] += 1
            logger.warning('抖音脚本响应异常 endpoint=%s status=%s', _safe_location(response.url), response.status)
        if not _is_douyin_host(response.url):
            return
        if _is_video_request(response.url):
            stats['video_responses'] += 1
            if response.status >= 400:
                stats['video_http_errors'] += 1
            logger.info('抖音视频响应 endpoint=%s status=%s content_type=%s', _safe_location(response.url), response.status, response.headers.get('content-type', ''))
        is_video = _is_video_request(response.url)
        if response.status == 200 and (is_video or 'json' in response.headers.get('content-type', '').lower()) and (is_video or len(pending_responses) + len(tasks) < 8):
            pending_responses[response.request] = response
            if is_video:
                stats['video_body_started'] += 1

    def on_request_finished(request):
        response = pending_responses.pop(request, None)
        if response is not None:
            if _is_video_request(response.url):
                stats['video_body_finished'] += 1
            task = asyncio.create_task(read_response(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    await context.route('**/*', route_request)
    page.on('request', on_request)
    page.on('requestfailed', on_request_failed)
    page.on('pageerror', on_page_error)
    page.on('response', on_response)
    page.on('requestfinished', on_request_finished)
    try:
        try:
            response = await page.goto(url, wait_until='commit', timeout=15000)
            stats['navigation_status'] = response.status if response else None
        except BrowserTimeout:
            stats['navigation_timeout'] = True
            logger.warning('抖音导航等待超时，继续监听视频响应')
        next_page_read = time.monotonic() + 1
        while True:
            stats['final_page'] = _safe_location(page.url)
            aweme_id = aweme_id or extract_aweme_id(page.url)
            stats['aweme_id'] = aweme_id
            if aweme_id:
                while payloads and (not matched):
                    matched = _find_video(payloads.popleft(), aweme_id)
                if not matched and time.monotonic() >= next_page_read:
                    item = await _read_page_data(page, aweme_id, stats)
                    matched = matched or item
                    next_page_read = time.monotonic() + 5
            if matched:
                video_urls = _video_urls(matched)
                logger.info('抖音匿名解析成功 aweme_id=%s candidate_count=%s elapsed_seconds=%.2f stats=%s', aweme_id, len(video_urls), time.monotonic() - started, stats)
                return {'aweme_id': aweme_id, 'resolved_url': page.url, 'video_url': video_urls[0], 'video_urls': video_urls, 'title': matched.get('desc') or '', 'headers': {'User-Agent': DEFAULT_USER_AGENT, 'Referer': page.url}, 'cookies': await context.cookies(video_urls)}
            if stats['captcha']:
                raise DouyinDownloadError('抖音要求验证码，当前服务器匿名会话无法解析；请稍后重试并检查 VPS 出口网络')
            await asyncio.sleep(0.25)
    finally:
        page.remove_listener('response', on_response)
        page.remove_listener('requestfinished', on_request_finished)
        pending_responses.clear()
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

def _diagnostic_code(stats: dict) -> str:
    if stats['captcha']:
        return 'CAPTCHA_REQUIRED'
    if stats['video_http_errors']:
        return 'VIDEO_HTTP_ERROR'
    if stats['video_request_failures']:
        return 'VIDEO_REQUEST_FAILED'
    if stats['video_empty_responses']:
        return 'VIDEO_EMPTY_RESPONSE'
    if stats['video_non_json_responses']:
        return 'VIDEO_NON_JSON_RESPONSE'
    if stats['video_json_responses']:
        return 'VIDEO_JSON_WITHOUT_MEDIA'
    if stats['video_body_read_timeouts']:
        return 'VIDEO_BODY_READ_TIMEOUT'
    if stats['video_body_read_errors']:
        return 'VIDEO_BODY_READ_ERROR'
    if stats['video_body_started'] > stats['video_body_finished']:
        return 'VIDEO_BODY_PENDING'
    if stats['script_http_errors'] or stats['script_request_failures']:
        return 'SCRIPT_LOAD_FAILED'
    if stats['page_read_timeouts'] >= 2:
        return 'PAGE_UNRESPONSIVE'
    if not stats['video_requests']:
        return 'NO_VIDEO_REQUEST'
    return 'VIDEO_DATA_MISSING'

async def _fetch(url, directory):
    counters = ('video_requests','video_responses','video_http_errors','video_request_failures','video_body_started',
                'video_body_finished','video_body_bytes','video_empty_responses','video_non_json_responses',
                'video_json_responses','video_body_read_timeouts','video_body_read_errors','json_responses','json_read_errors',
                'request_failures','invalid_requests','script_errors','script_http_errors','script_request_failures',
                'page_read_timeouts','page_read_errors','blocked_resources')
    stats = dict.fromkeys(counters, 0)
    stats.update(captcha=False, video_loading=False, ready_state='unknown', navigation_timeout=False,
                 anonymous_context=True, historical_state_loaded=False, windows_ua=True)
    timeout = int(os.getenv('DOUYIN_BROWSER_TIMEOUT_SECONDS', '60'))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chromium', headless=True, timeout=15000)
        context = await browser.new_context(user_agent=DEFAULT_USER_AGENT,locale='zh-CN',timezone_id='Asia/Shanghai',
                                            viewport={'width':1440,'height':900})
        try:
            result = await asyncio.wait_for(_parse_douyin_page(context,url,stats),timeout=timeout)
            stats['matched_id'] = result['aweme_id']
            stats['candidate_count'] = len(result['video_urls'])
            stats['anonymous_cookie_count'] = len(result['cookies'])
            stats['diagnostic'] = 'MATCHED'
            return result
        except (asyncio.TimeoutError,DouyinDownloadError):
            code = _diagnostic_code(stats)
            stats['diagnostic'] = code
            if code == 'CAPTCHA_REQUIRED':
                raise Failure('verification_required') from None
            if code == 'VIDEO_EMPTY_RESPONSE':
                raise Failure('douyin_empty_response') from None
            if code == 'SCRIPT_LOAD_FAILED':
                raise Failure('douyin_script_failed') from None
            if code in {'VIDEO_JSON_WITHOUT_MEDIA','NO_VIDEO_REQUEST','VIDEO_DATA_MISSING'}:
                raise Failure('unavailable') from None
            raise Failure('douyin_parse_timeout') from None
        except BrowserError:
            stats['diagnostic'] = 'BROWSER_ERROR'
            raise Failure('download_failed') from None
        finally:
            atomic_json(directory/'douyin-diagnostics.json',stats)
            await context.close()
            await browser.close()


def fetch_meta(url,directory):
    return asyncio.run(_fetch(url,directory))
