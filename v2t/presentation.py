"""User-facing names and evidence-based, non-secret error explanations."""
import re,unicodedata

def short_title(title, fallback='视频'):
    text=re.sub(r'https?://\S+','',str(title or ''))
    text=''.join(c for c in text if not unicodedata.category(c).startswith('C'))
    text=re.sub(r'[<>:"/\\|?*]',' ',text)
    text=' '.join(text.split()).strip(' .')
    chinese=bool(re.search(r'[\u3400-\u9fff]',text))
    if chinese:text=text[:20]
    else:text=' '.join(text.split()[:10])[:120]
    text=text.strip(' .') or fallback
    if text.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:text='视频_'+text
    return text

def filename(title,kind,extension='md',fallback='视频'):
    return f'{short_title(title,fallback)}_{kind}.{extension}'

HINTS={
 'invalid_input':'地址错误：未识别到受支持的视频链接。请发送具体的抖音作品、YouTube 视频或 X/Twitter 视频链接。',
 'download_failed':'下载失败：未取得完整媒体。可能是链接不可访问或网络请求失败；请确认链接能播放，稍后重试。当前证据不足以确定具体原因。',
 'network_error':'下载失败：连接、DNS 或网络传输异常。请检查网络，稍后重试。',
 'adapter_memory_limit':'下载失败：Windows 浏览器下载进程超过内存预算。不是 GPU 显存不足；可尝试较小视频，或调整下载内存预算后重试。',
 'gpu_oom':'识别失败：GPU 显存不足。请等待其他 GPU 工作结束后重试；已下载视频保留。',
 'gpu_unavailable':'识别失败：GPU 或 CUDA 不可用。需检查 GPU 环境；未回退到 CPU 或云端。',
 'douyin_empty_response':'下载失败：未能取得抖音作品信息。详情内容为空，尚不能确定是网络路径还是平台限制；请稍后重试。',
 'verification_required':'下载失败：抖音要求验证码或登录，匿名下载已停止。请换一个公开视频或稍后重试。',
 'third_party_unavailable':'下载失败：X/Twitter 使用的 fxtwitter 服务不可用或没有返回视频。请确认帖子有视频，稍后重试。',
 'unavailable':'未能识别到可访问的视频信息：作品可能已删除、私密或不支持匿名访问。',
 'no_media':'未取得有效媒体或可解码音轨，请确认链接包含可播放视频。',
 'no_video':'下载内容没有视频画面，无法作为视频发送；未进行转写。',
 'send_too_large':'视频已下载，但超过当前 Telegram 云端上传上限（50 MB），无法直接发送。媒体已保留；重试不能解决大小限制。',
 'send_forbidden':'发送失败：机器人无权向该聊天发送。请先打开测试机器人并发送 /start，确认没有屏蔽机器人，再重试发送。',
 'send_rate_limited':'发送失败：Telegram 暂时限制发送频率，请稍后重试。已完成的下载和识别结果保留。',
 'send_failed':'发送失败：Telegram 未确认收到附件，可能是网络或聊天权限问题。请稍后重试，只补发未确认的附件。',
 'polish_failed':'DeepSeek 整理失败：原稿已保存并优先发送。请检查 API 配置、额度或网络后重试；不会重新下载和识别。',
 'timeout':'处理超时：本次未能在期限内完成。可能是网络缓慢或处理耗时较长；稍后重试，将复用有效结果。',
 'storage_unavailable':'暂存目录读取失败，不能确认空间用量。可能是临时文件访问冲突或目录权限问题，请稍后重试；这不表示磁盘已满。',
 'disk_full':'暂存磁盘剩余空间不足，请处理空间后重试；不会自动删除文件。',
 'adapter_quota':'暂存目录总额度不足，请检查保留文件或调整额度后重试；不会自动批量清理。'
}
def error_text(code,defaults):return HINTS.get(code,defaults.get(code,defaults['internal_error']))
