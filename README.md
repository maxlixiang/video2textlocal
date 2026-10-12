# Telegram 视频转文字机器人

独立 Linux/Docker 项目，不修改 Video2Text1 或旧机器人部署。第一版使用云端 Telegram Bot API 和长轮询，仅允许独立测试机器人启动。实际验收状态见 [TEST-REPORT.md](TEST-REPORT.md)，不要把代码实现或镜像构建成功等同于三平台验收通过。

## 功能与结构

用户发链接/分享文本 → 选择视频下载、原稿或原稿＋DeepSeek 整理稿。视频下载仅下载并发送媒体；原稿使用本地 GPU 识别；整理模式先发送原稿，再处理和发送 DeepSeek 整理稿。

- YouTube：yt-dlp，自动语言识别，默认 Faster-Whisper。
- X/Twitter：旧机器人 fxtwitter 固定 MP4 直链，默认 Faster-Whisper。第三方失效返回明确错误。
- 抖音：可选 Windows 主动领取适配器，使用干净匿名 Playwright Chromium 上下文；当前 WSL/Docker 详情接口零正文，不能假设 Linux 直下载可用。默认中文 FunASR，支持热词。
- 提交前可用按钮切换引擎；一次只运行所选引擎。
- Markdown UTF-8 附件，原稿、整理稿分别命名；原稿带时间戳。没有说话人分离或 SRT/VTT 导出。
- 原稿模式不依赖 DeepSeek 密钥；整理只发送转写文本，不发送媒体、不默认翻译/总结/正式文章。

`v2t/manager.py` 是机器人和任务管理唯一 SQLite 写入者。`v2t/service.py` 是内部下载/GPU HTTP 服务。GPU 服务并发 1，每次启动独立推理子进程，子进程退出后释放模型和 CUDA 上下文，不常驻两套模型，不回退 CPU/云端。冷启动每次加载模型，换取明确显存释放。

SQLite 的 tasks、events、deliveries 分别记录任务、各阶段历史、确认发送的附件内容哈希。manager 文件锁防止同一数据库启动多个管理者。回调检查白名单和任务归属；重复提交只更新同一任务。

## 环境与构建

需要 Docker Desktop WSL2 后端或已配置 NVIDIA 容器运行能力的 Linux Engine。模型和数据库放在 Linux Docker volumes 中。不会自动安装驱动、改网络或启动设置。

```bash
cd /home/codex/workspace/telegram-video2text
python3 build_tools/fetch_wheels.py
docker compose --env-file .env.example config --quiet
docker build --target manager -t telegram-video2text-manager:local .
docker compose --env-file .env.example build download gpu
```

当前连接会话若尚未刷新 docker 组，可使用 `sg docker -c 'docker version'`。这是临时使用已有用户组，不是修改权限；也可重新连接会话后检查 `id` 和 `docker version`。不要将 socket 改为 666，不需要免密 sudo。

模型按固定 revision 下载，并生成包含权重内容哈希的 `models.lock.json`。下载完成并不表示 GPU 实测通过。

```bash
docker compose --env-file .env.example --profile tools run --name v2t-model-prepare models
docker compose --env-file .env.example up -d download gpu
docker compose --env-file .env.example --profile tools run --name v2t-gpu-verification verify python -m v2t.verify --gpu
docker compose --env-file .env.example --profile tools run --name v2t-douyin-verification verify python -m v2t.verify --douyin
```

验证工具使用公开语音样本做 FunASR → Whisper → FunASR 的实际非空 GPU 推理，记录实际设备、精度、包版本、模型锁哈希和时间。抖音验证每个样本两次、每次新任务目录和新匿名上下文，检查目标 ID、完整下载和全音轨解码，写 `verification/*.json`。本次抖音 16 次实测未取得可下载媒体，出现过验证码并明确拒绝继续；详见测试报告。两套 GPU 引擎均实际推理通过。

每次 `run` 请使用新的明确容器名，或者由用户手工处理上一次退出的容器；不自动批量清理。所有命令均不使用 `--rm`、volume 删除或 prune。

## 独立测试机器人配置与启动

在本机将 `.env.example` 复制成 `.env.test`，填写独立测试 Token、对应 `EXPECTED_TEST_BOT_ID` 和数字白名单 `ALLOWED_USER_IDS`。不要把 Token 粘到聊天或提交到 Git；不要使用生产 Token。设置 `BOT_PURPOSE=test`。启动前 `getMe` 必须与配置的测试 ID 相符；没有有效配置不会开始轮询。

```bash
docker compose --env-file .env.test --profile bot build manager
docker compose --env-file .env.test --profile bot up -d manager
```

向机器人发一条公开视频链接，点击输出按钮。每条消息处理第一个有效链接；多条链接请分开发。任务失败后点“重试未完成阶段”。`/status` 查看自己当前聊天最近 10 个任务。

DeepSeek 的地址、模型、超时、上下文预算、输出预算和提示词在配置中统一。`DEEPSEEK_PROMPT` 可覆盖默认提示词，修改时也应修改 `PROMPT_VERSION`。Token 预算采用 UTF-8 字节的保守上界并预留提示词、包装和输出空间，不声称是 DeepSeek 精确分词器。单片段超预算明确报错，不越过片段边界强行切断。只接收 `finish_reason=stop` 且正文非空的块；成功块立即保存，失败后从缺块继续。提示词约束不是忠实度自动验收，应人工抽查。

## 停止、恢复和数据

```bash
docker compose --env-file .env.test --profile bot stop manager
docker compose --env-file .env.example stop download gpu
# 保留数据启动，running 任务自动回到队列，从有效结果继续
docker compose --env-file .env.test --profile bot up -d
```

不要运行 `down -v`、`docker system prune`、批量删除脚本或旧项目清理逻辑。失败临时文件和退出测试容器保留，清理请由用户手工决定；程序不提供自动批量清理。

独立 volumes：models `/models`、media `/media/<task_id>`、results `/results/<task_id>`、database `/database`。媒体先写临时路径，通过大小、时长、音轨检查及 FFmpeg 完整解码后提交为 `media.bin`、`audio.wav`；扩展名不用于判断媒体格式。结果 JSON/块采用临时文件替换。下载总超时 600 秒、默认 500 MiB/2 小时；下载服务最多 2 个任务，抖音浏览器最多 1 个，manager 第一版串行执行任务。

完整媒体复用发生在在线解析之前；发送失败时直接使用完整转写结果，整理失败只补整理。缓存键包括媒体/音频 SHA-256、引擎及模型参数、模型版本和权重哈希；整理缓存另外包括原稿、提示词版本、提示词内容和 API 参数。文件存在本身不视为缓存有效。

Telegram 发送采用“收到成功响应后落盘”策略。云端发送成功但响应丢失、或成功后落盘前崩溃的极小窗口可能重复附件，不能保证严格 exactly-once；已经确认的附件不会重复发送。正常重复按钮点击不会创建第二个任务。

## 故障排查

- Docker 权限：`id`、`getent group docker`、`stat /var/run/docker.sock`；已在组中但会话未加载时重新连接或临时 `sg docker`。新加组需要由用户手动执行，不修改 socket 模式。
- 无说话内容：返回 `empty_transcript`，不制造文字、不自动换引擎；本次 X 样本已由用户确认属于此情况。
- GPU：查看任务错误 `gpu_unavailable` / `gpu_oom`；必须通过实际推理验证，`nvidia-smi` 成功不充分。不会静默 CPU/云端回退。
- 模型：需先完成 models profile；模型版本变化需重新生成模型锁；热词变化仅使转写缓存失效，无需重新下载模型。权重哈希不一致拒绝缓存和推理。
- 抖音：`verification_required`、`target_mismatch`、`unavailable`、`download_failed`、`douyin_empty_response`、`douyin_script_failed`。当前出口匿名接口空响应是已实测限制，Windows UA 不保证成功。匿名 Cookie 只在当前上下文内使用，不保存登录状态。诊断仅记录作品 ID、导航状态、验证标志和 Cookie 数量，不记录值、响应体或完整媒体 URL。不得自动绕过验证码。
- X：`third_party_unavailable` 是直链不可用、响应异常或缺有效 MP4 音轨。第一版只处理推文中的第一个视频，不合并多视频。
- 整理：`deepseek_missing` 不影响已发送原稿；`polish_truncated` 不提交截断块；改变提示词后旧块失效。
- 发送：失败按钮重试未确认发送的附件。云端 Bot API 文件大小限制也可能导致 `send_failed`。
- 运行日志只输出固定错误码，不输出 SDK 异常全文。请勿公开 `.env.test`、数据库和带私人原文的结果。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

这些离线测试使用假 Telegram/服务，验证业务规则，不能替代真实 Telegram、网络下载或 GPU 验收。测试临时目录故意保留，没有自动递归删除。

下载流程保留 yt-dlp / fxtwitter / Windows-UA Playwright 路线；旧仓库已按远端确认的提交读取，复用了匿名解析和固定 MP4 下载路线。代码来源比较和保护范围见 [AUDIT.md](AUDIT.md)。

## 当前网络的测试覆盖配置

当前出口发现 fake-IP DNS（198.18/15）。这里仅对已知媒体/平台域名启用兼容，不改变宿主代理。需要这种网络时在 Compose 命令中加 `-f compose.yaml -f compose.test-network.yaml`；开发测试可另外加 `-f compose.dev.yaml` 只读挂载源码。普通公网 DNS 不需要覆盖配置。

GPU 构建使用 `wheelhouse` 离线安装，避免构建时重新下载大包。`build_tools/fetch_wheels.py` 读取固定版本清单，从已测包镜像下载，并按官方 PyPI 元数据逐项校验 SHA-256，生成 `wheelhouse/manifest.json`；它不在宿主安装包。已存在且哈希正确的包直接复用。基础镜像固定 digest，Python 依赖固定版本；APT 的 FFmpeg/浏览器系统库来自构建时 Debian 仓库，尚未做到所有系统包的离线快照复现。

当前出口启动下载/验证时使用：

```bash
docker compose --env-file .env.example -f compose.yaml -f compose.test-network.yaml up -d download gpu
```

原稿下载与 GPU 验证完成后，可用已提交的媒体任务 ID 测试识别，不重新解析或下载：

```bash
docker compose --env-file .env.example --profile tools run --name v2t-existing-media-check verify python -m v2t.verify --existing <task_id>
```

## 可选 Windows 抖音适配器

已在独立项目实现，默认关闭。手动前台运行、mTLS 交接、租约和恢复使用说明见 [ADAPTER-README.md](ADAPTER-README.md)，实际验收与限制见 [ADAPTER-TEST-REPORT.md](ADAPTER-TEST-REPORT.md)。一个真实作品已完成 Windows 下载→Docker FunASR 原稿；独立 Telegram/DeepSeek 真实验收尚缺配置。

## 三种输出与标题附件

新增视频下载、发送原稿、原稿＋DeepSeek 整理稿三个按钮，详见 [INTERACTION-README.md](INTERACTION-README.md)。实际视频/原稿/整理稿发送与限制见 [本轮测试报告](verification/interaction/REPORT.md)。

## 热词与整理稿时间戳

整理稿不再输出时间戳，原稿保留。用户热词表及整理名称对照位于 config，修改与缓存说明见 [TERMINOLOGY-README.md](TERMINOLOGY-README.md)。

## 仓库交付范围

仓库仅包含源码、构建文件、固定依赖清单、无密钥配置示例和测试报告摘要。测试媒体、转写附件、原始运行日志、证书/私钥、模型缓存、wheelhouse 和旧项目参考副本留在本地，不随源码发布。部分历史报告引用的原始本机证据不在仓库中。克隆后请先执行上面的 fetch_wheels.py，再构建 GPU 镜像；wheelhouse 不通过 Git 分发。
