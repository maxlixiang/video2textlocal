"""Pure matching helpers reused from old repository at 92b869be0569eaf0cdd4fd17f2a2081a6484deef."""
from urllib.parse import urlparse,parse_qs

def extract_aweme_id(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split('/') if part]
    for index, part in enumerate(parts[:-1]):
        if part in {'video', 'note'} and parts[index + 1].isdigit():
            return parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ('aweme_id', 'modal_id', 'item_id'):
        value = query.get(key, [None])[0]
        if value and value.isdigit():
            return value
    return None

def _video_urls(item: dict) -> list[str]:
    video = item.get('video') or {}
    if not isinstance(video, dict):
        return []
    addresses = [video.get(key) for key in ('play_addr', 'playAddr', 'play_addr_h264', 'play_addr_265')]
    for variant in video.get('bit_rate') or []:
        if isinstance(variant, dict):
            addresses.append(variant.get('play_addr'))
    urls = []
    for address in addresses:
        if isinstance(address, str):
            candidates = [address]
        elif isinstance(address, dict):
            candidates = address.get('url_list') or address.get('urlList') or []
        else:
            continue
        for candidate in candidates:
            if isinstance(candidate, str) and urlparse(candidate).scheme in {'http', 'https'} and (candidate not in urls):
                urls.append(candidate)
    return urls

def _find_video(payload, aweme_id: str) -> dict | None:
    if isinstance(payload, dict):
        item_id = payload.get('aweme_id') or payload.get('awemeId') or payload.get('item_id')
        if str(item_id) == aweme_id and _video_urls(payload):
            return payload
        for value in payload.values():
            found = _find_video(value, aweme_id)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_video(value, aweme_id)
            if found:
                return found
    return None
