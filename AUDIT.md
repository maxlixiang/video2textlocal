# 只读核查与实现依据

日期：2026-10-12，Asia/Shanghai。

## 环境

- 主机 `justdoit`，内核 `6.6.87.2-microsoft-standard-WSL2`，Ubuntu 24.04.5 LTS。
- 宿主 GPU 查询：NVIDIA GeForce RTX 4060 Ti，8188 MiB，驱动 610.88。此项不是 ASR 验收。
- Docker Desktop WSL2 后端，Desktop 4.94.0，Engine/CLI 29.8.2，Compose 5.5.1。配额 12 CPU，16692482048 bytes RAM。
- Docker Root `/var/lib/docker`；socket `/var/run/docker.sock`，实际 root:docker (0:1001)，660。
- 账号 codex UID/GID 1000；当前会话 groups 为 codex/sudo，组数据库 docker 包含 codex。用 `sg docker` 已成功连接，不修改权限。
- 核查时无运行中的 Docker 容器；宿主监听 2222 和 DNS 53。新服务不发布宿主端口。
- Linux 工作盘 `/dev/sdd`，核查时约 954 GiB 可用；独立项目创建前目录不存在。
- 无凭据 HTTPS：YouTube/X/抖音/Telegram/Hugging Face/ModelScope/PyPI 返回 200；fxtwitter 根路径返回 301，DeepSeek 401，Docker registry 根路径 404。证明能建立 HTTPS，不证明业务 API或容器出口可用。

## 保护范围

Windows 原项目 `/mnt/c/Users/justd/Desktop/Video2Text1` 存在且只读核查。

读取了四个核心脚本、README、requirements、热词和测试/历史设计文本。未导入或运行源项目模块，未读取 .env、浏览器会话、日志敏感内容；未复制媒体、模型或虚拟环境。四个源文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| dy.py | 32263284e3cada9b0cb94aa4234292539fb22f3885b0ebe93c3af86652f8c5fd |
| video_to_text.py | e717c408958f6f3f6d634a73a0ce28761b541ec23cfdddcdb451d2b8094fe613 |
| funasr_asr.py | 603182c72acdd1090f5f87cae7790ae9b65ffbe3f24a06faa357d1c0394cae57 |
| polish_article.py | 034dd0b6a300bddf56379385ba2ea24c0cbdb387948ca7a1a7220cd7cc859d8e |

旧机器人仓库：`maxlixiang/Telegram-Media-AI-Bot`。最初认证失败/404；用户改为 Public 后再次查询远端 HEAD，实际确认当前提交为 `92b869be0569eaf0cdd4fd17f2a2081a6484deef`，恰好与参考版本相同。源码按此不可变提交读取，脱敏只读副本与各文件原始 SHA-256 记录在 `reference-audit/manifest.json`。没有修改、推送或启动旧项目。

已读：main.py、downloader.py、twitter_downloader.py、douyin_downloader.py、ai_services.py、Dockerfile、docker-compose.yml、requirements.txt、README.md。未取真实配置、浏览器状态或清理脚本。笔记本 F 盘不是 justdoit 路径，澄清后不再查找。

## 两套抖音实现比较与选择

| 比较项 | Video2Text1 的 dy.py | 旧机器人当前代码 | 新实现选择 |
|---|---|---|---|
| 浏览器 | Windows UA，Chrome/Edge/Chromium；默认 headless shell 路径可能不同 | 完整 Chromium `channel="chromium"`，Windows UA，上海时区 | 复用旧机器人完整 Chromium；固定 Playwright 1.58.0 |
| 成功条件 | fetch_detail() 取首个 captured 详情 | 网络响应＋页面嵌入数据两条路径 | 复用旧解析器，另要求实际下载及完整音轨解码 |
| ID 匹配 | 未显式核对 aweme_id 与目标 | `_find_video()` 递归核对 aweme_id/awemeId/item_id | 保留；短链先从独立跳转提取目标 ID |
| 候选地址 | 只选最高档并遍历该档 URL | play_addr/playAddr/H264/H265、码率档，多备用地址 | 复用 `_video_urls()`，去重并最多尝试 6 个 |
| 页面读取 | domcontentloaded＋固定等待 | commit 导航，requestfinished 后读正文，DOM evaluate 限时 | 保留旧异步超时、正文时序和页面回退 |
| 匿名 Cookie | 可加载保存 .douyin_state.json | 新匿名 context，不加载历史状态，Cookie 域/路径作用域 | 保留；CookieJar 处理重定向作用域，不落盘 Cookie 值 |
| 下载校验 | HTTP 成功＋至少 2048 字节 | 流式 MP4 ftyp＋Content-Length | 复用检查，新增大小/时长限制、全音轨解码、临时提交和哈希 |
| 诊断 | 页面关键词和导航错误 | API 状态/字节数、脚本/响应/页面超时分类 | 保留脱敏 stats，输出固定错误码；日志不显示响应体或签名地址 |

选择旧机器人解析器而不是 Video2Text1 的首个响应策略，原因是 ID 正确性、页面数据回退、完整 Chromium 和更细诊断。新项目 `douyin_parser.py`/`douyin_data.py` 标明移植提交。旧解析器保留无历史状态；没有加入登录、验证码绕过或反复无限重试。

当前出口 DNS 把部分公开域名映射到 198.18/15，首轮安全地址检查拦截了这些地址。`compose.test-network.yaml` 只允许该 synthetic range 内的已知平台/CDN域名；仍拒绝 loopback/RFC1918/link-local，不改宿主网络、不关闭 TLS。后续失败必须与首轮代码拦截区分。

## 旧机器人其他代码核查

- `downloader.py::sync_download()`：YouTube/通用音频走 yt-dlp `bestaudio/best`，原后处理转 MP3；新项目保留 yt-dlp 路线，改为本地 ASR 的 16kHz WAV，并增加限额/超时。
- `twitter_downloader.py::build_fxtwitter_mp4_url()`：实际是 `https://fxtwitter.com/i/status/<id>.mp4`，不是状态 JSON API。新项目已改为这个确切端点并保留流式/MP4 校验；第三方不可用明确报错。
- `ai_services.py::process_groq_transcription()` 使用 Groq 云端 whisper-large-v3；整理用 llama-3.3-70b-versatile。新项目不复用云端识别，改成本地两引擎和可选 DeepSeek。
- `main.py::button_callback()` 先发送媒体再识别；新项目原稿发送独立于媒体发送，且原稿先于整理。
- `main.py` 启动硬编码本地 Bot API 127.0.0.1:8081，Compose 使用 host network 与共享目录。新项目改云端 Bot API、内部 Docker 网络，无宿主端口。
- 旧 main.py 调度定期清理、任务尾部调用 cleanup_task_files；新项目没有复用这两条批量清理路径。
- 旧链接任务存在 context.user_data，无 SQLite；按钮没有显式再次白名单检查和数据库原子去重。新项目加入持久任务、归属核查与唯一提交。

## 其他原代码复用与变化

- video_to_text.py::extract_audio_with_ffmpeg() 的 16kHz/mono/PCM 参数保留。
- get_whisper_model()/transcribe_audio() 的 Faster-Whisper 与 VAD 思路保留，但取消 CPU 回退，不采用进程内双模型缓存。
- funasr_asr.py::build_model()/load_hotwords() 的 Paraformer+VAD+标点与热词路线保留；统一时间单位为秒，处理全部结果，不只 res[0]。
- polish_article.py 正式文章/翻译行为不保留。新整理提示词只忠实断句分段，按预算分块、检查 finish_reason、逐块保存。
- 原 manifest 的绝对路径/文件存在跳过机制改为 UUID、SQLite 事件及内容/配置/模型/提示词哈希。
- 没有沿用旧项目批量清理或本地 Bot API 硬编码。

## 官方依据

- Faster-Whisper CUDA/CTranslate2：[项目 README](https://github.com/SYSTRAN/faster-whisper)。
- FunASR 模型和 Python API：[官方 API 文档](https://github.com/modelscope/FunASR/blob/main/docs/python_api.md)。
- yt-dlp 限额和超时：[官方 README](https://github.com/yt-dlp/yt-dlp/blob/master/README.md)。
- fxtwitter MP4 API：[Status Fetch API](https://github.com/FxEmbed/FxEmbed/wiki/Status-Fetch-API)。
- DeepSeek 截断信号：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

构建基础镜像已记录实际 registry digest。最终依赖/模型可用性和显存表现以 TEST-REPORT 及实际证据为准。

固定 FunASR 1.2.7 wheel 进一步核查：paraformer-zh 实际映射到 SeACoParaformer（支持热词），ct-punc 映射到 cn-en-common-vocab471067-large。新项目用显式模型 ID 保留这两个映射，并记录 ASR/VAD/标点组件的实际设备和 dtype，避免普通 Paraformer 静默忽略热词。
