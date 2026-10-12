# 三种输出与附件命名

发送一个抖音、YouTube 或 X/Twitter 视频链接或分享文本后，机器人提供：

- **视频下载**：只下载并校验媒体，返回视频；不调用 ASR 或 DeepSeek。
- **发送原稿**：本地 GPU 语音识别，带时间戳；不调用 DeepSeek。
- **发送 DeepSeek 整理稿＋原稿**：先保存并发送原稿，再把文本交给 DeepSeek 忠实整理，分别发送两个附件。

仍提供任务级引擎切换，抖音默认 FunASR，YouTube/X 默认 Faster-Whisper。白名单、按钮归属检查、重复点击去重、失败阶段重试和持久化恢复保持有效。每条链接建立一个任务，选择后不再切换输出；需要另一个输出可再发送该链接。

## 标题

中文/中英混合标题取前 20 个字符（包括标点），纯英文取前 10 个空格分隔单词，并限制文件名长度。移除换行、路径/文件系统非法字符及标题中的 URL。附件分别为 `标题_视频.mp4`、`标题_原稿.md`、`标题_deepseek转写.md`。非 MP4 视频按实际格式作为文件发送。

YouTube 使用 yt-dlp 标题，抖音使用匹配作品的 desc，X 使用同一 fxtwitter 服务的帖子正文作为标题；可选标题查询失败不影响已经下载的 MP4。没有标题的旧缓存或无正文帖子使用平台和作品 ID，避免猜造标题。内部任务目录仍使用独立 UUID。

YouTube 视频模式选含画面和音轨的单文件格式（优先 MP4），不承诺最高分辨率；原稿模式保持既有音频下载。纯音频缓存不能充当视频。无声视频可下载发送，但转写会明确提示没有音轨。

## 上传与错误

当前使用云端 Telegram Bot API，[官方上传上限](https://core.telegram.org/bots/api#sending-files)为新上传文件 50 MB。本实现以 50,000,000 字节保护，超限保留已下载媒体并明确反馈；不会自动压缩、分片、发布公开下载链接或改变为本地 Bot API。下载上限与发送上限分别执行。

上传采用已知长度的 multipart 流，每次读 64 KiB，不在 manager 中把整个视频读入内存。MP4 使用 sendVideo，其他格式使用 sendDocument。

地址不支持时反馈“地址错误”；无作品信息、验证码、下载内存预算、GPU 显存、网络连接、磁盘额度、Telegram 权限/频率和超限分别提示原因或处理建议。仅明确的连接/DNS/超时证据归为网络故障，其他下载异常只说明可能原因，不把所有失败断言为网络或平台风控。发送失败重试有效附件，整理失败只重跑缺失整理块。

## 测试配置与启动

本机用户已经填写新项目 `.env`，无需再次复制密钥。基础 Compose 默认读取 `.env.test`；使用现有独立测试配置时显式设置 `BOT_ENV_FILE=.env`。manager 仍强制 BOT_PURPOSE=test、机器人 ID 匹配和白名单。

```bash
export BOT_ENV_FILE=.env
export WINDOWS_ADAPTER_ENABLED=1
export ADAPTER_CREDENTIALS_DIR=/home/codex/workspace/telegram-video2text/.adapter-pki
docker compose --env-file .env -f compose.yaml -f compose.adapter.yaml --profile bot up -d
```

上述证书为短期测试证书，过期后必须按 ADAPTER-README.md 更新，不能当长期部署凭据。Windows 前台工作进程和停止/恢复方法见该文档；不开生产机器人、不注册 Windows 服务或计划任务。

实际本轮测试记录见 `verification/interaction/REPORT.md`；不要把本地分派的测试回调称作用户真实按钮点击。

DeepSeek 整理默认显式设置 `DEEPSEEK_THINKING=disabled`，与输出预算及提示词统一配置并纳入缓存键。实际检测到截断时不会发送半份整理稿，成功块保留，重试缺失块。
