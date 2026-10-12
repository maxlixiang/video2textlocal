# 测试记录

2026-10-12，justdoit 实际 WSL2/Docker Desktop 出口。代码、镜像构建、模拟测试和真实平台验收分别记录；没有启动任何 Telegram 长轮询。

| 检查 | 状态 | 证据与边界 |
|---|---|---|
| 原项目保护/只读审计 | 通过 | 四个关键源文件 SHA-256 记录在 AUDIT.md；未运行或修改 |
| 旧仓库当前源码 | 通过 | 重新查询远端 HEAD：92b869be0569eaf0cdd4fd17f2a2081a6484deef；读取不可变提交文件，见 reference-audit/manifest.json |
| WSL/Docker/GPU/出站 | 通过 | Ubuntu 24.04.5；Desktop 4.94.0/Engine 29.8.2；RTX 4060 Ti 8188 MiB，驱动 610.88；宿主及下载容器 HTTPS 可达不等于平台业务成功 |
| 构建/固定依赖 | 通过 | 下载镜像 pip check、GPU 离线安装 pip check；50 项额外 GPU 包固定版本与官方 SHA-256；基础镜像固定 digest |
| 离线业务回归 | 通过 | 最终 manager 镜像内 15 个独立测试，0.786 秒全部通过；覆盖权限、去重、缓存、阶段续跑、截断与原稿无密钥 |
| FunASR 实际 GPU 推理 | 通过 | CUDA float32；ASR/VAD/标点三组件参数均在 CUDA；两次各 36 个片段，23.218/22.888 秒 |
| Faster-Whisper 实际 GPU 推理 | 通过 | CUDA float16，自动识别中文，31 个片段，5.730 秒 |
| 模型切换/显存释放 | 通过 | FunASR→Whisper→FunASR，独立子进程；退出后整卡显存回到约 1860–1917 MiB；无 CPU/云端回退 |
| YouTube 下载→GPU→原稿 | 通过 | 用户样本 G14CnqM70Cw；完整音轨解码，83.581 秒；Whisper 自动英语，56 个片段，UTF-8 带时间戳原稿 |
| X 下载→GPU 无说话结果 | 通过（预期空结果） | 用户样本 2109283998501625898；MP4 27,527,549 字节、74.861 秒，完整音轨解码；实际 CUDA float16 推理返回 empty_transcript；用户确认视频无说话内容。不是非空识别质量验收 |
| 抖音容器匿名下载 | 失败 | 8 种输入×2 轮=16 次，0 次完成媒体下载；短链/分享文本正确得到用户目标 ID 7695089785269996809，但匿名视频接口主要返回空内容 |
| 验证码与错误反馈 | 部分通过 | 实测 CAPTCHA_REQUIRED，明确 verification_required，无绕过；空响应复核返回 douyin_empty_response 与中文诊断；失效/不可访问负例部分同样空响应，无法证明精确分类全部通过 |
| 完整媒体离线复用 | 通过 | network=none 容器，复用已完成媒体；metadata 崩溃窗口也能本地解码恢复，不重新在线解析 |
| 容器崩溃/重启恢复 | 通过（发送模拟） | 第一阶段强制退出 87，重启后恢复同任务；已确认原稿不重发，下载/GPU 调用 0 次，继续整理至 deepseek_missing；Telegram 收据模拟，未调用真实 DeepSeek |
| 整理失败只补整理/发送失败只补发送 | 通过（模拟） | 单元测试覆盖逐块续跑、提示词失效、截断拒绝、完成整理缓存复用、确认发送去重 |
| 三平台真实 Telegram 两种输出 | 尚未验证 | 独立测试 Token/白名单尚未准备；抖音匿名下载仍受阻 |
| DeepSeek 实际整理与忠实度 | 尚未验证 | 无测试密钥；未发送原文到外部 API |

## 实际 GPU 与模型

证据：verification/gpu.json、verification/youtube-gpu-pipeline.json、verification/x-no-speech-acceptance.json。两套大模型没有同时常驻。首次切换测试整卡 nvidia-smi 峰值 4349 MiB（约 4.25 GiB）；最终镜像复测峰值 4641 MiB（约 4.53 GiB），其中包含其它进程。首次基线约 1860–1951 MiB，复测基线 2040 MiB，不能把整卡峰值当作模型独占显存。FunASR Torch peak allocated 为 2,381,435,904 字节。此记录来自短样本，不能保证长稿或其他参数下不 OOM。

实际通过版本：Torch/torchaudio 2.5.1+cu121，FunASR 1.2.7，Faster-Whisper 1.2.1，CTranslate2 4.6.0。Whisper large-v3-turbo 仓库 revision 为 0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf；FunASR SeACo Paraformer、FSMN VAD、大词表标点均 v2.0.4，权重内容另由模型锁校验。模型参数和热词见 GPU 证据与配置示例。

## 抖音隔离诊断

干净 Linux Chromium、Windows UA、无 storage_state/登录 Cookie；当前匿名上下文产生的 Cookie 可传到对应域下载。移植旧仓库的目标 ID 匹配、requestfinished 读取、媒体候选与页面 JSON 回退，并使用完整 Chromium 新无头模式。

当前网络使用 fake-IP DNS。初次 guard 拒绝后，仅在新项目覆盖文件中放行已知平台域名的 198.18/15；没有修改宿主网络，也没有放开私网地址。后续 16 次诊断：VIDEO_EMPTY_RESPONSE 13、SCRIPT_LOAD_FAILED 1、CAPTCHA_REQUIRED 1、NO_VIDEO_REQUEST 1。HTTP 200 或解析到 ID 不视为下载成功；没有实际媒体与可解码音轨，因此判失败。不能仅由现有证据断定是出口风控或浏览器指纹的单一原因。

开发挂载期间新增错误码后，旧服务进程的映射曾把部分失败显示成 internal_error；原始诊断保留在 verification/douyin-development-run.json。统一重启自有测试服务后，空响应中文反馈已复核。没有无限重试、登录或改为 Windows 下载服务。

## 恢复与交付边界

verification/media-resume.json、verification/recovery-phase1.json、verification/container-recovery.json 记录真实容器离线复用及重启，但发送层使用模拟收据。最终 Telegram 和 DeepSeek 验收须使用独立测试机器人与密钥，当前暂缺配置不影响原稿代码和 GPU 管线验证。X 依赖第三方 fxtwitter；发送成功但响应丢失/落盘前崩溃仍可能重复附件，不能保证严格 exactly-once。

测试媒体、模型、结果、退出容器与测试临时目录保留，不自动清理。未启动生产部署，未修改 Windows 驱动、socket 权限、系统网络或旧机器人。完整系统依赖尚未锁定 Debian 快照；高并发、长视频、真实热词效果及整理质量需要后续样本验收。

## 最终镜像复核

移除源码开发挂载，使用最终构建镜像：Whisper CUDA float16 再次转写 YouTube，57 个片段、15.168 秒；FunASR CUDA float32 再次转写公开中文语音，36 个片段、24.279 秒。两次均在子进程退出后回到 2040 MiB。Whisper 首次 56 个片段与复测 57 个片段属于实际运行结果，未声称逐次字节一致。证据见 verification/final-whisper.json、final-funasr.json、final-unit.log、final-image-ids.txt、final-gpu-packages.json、final-static-check.json。源码与中文文档共 20 个文件 UTF-8 回读/AST 检查通过。

本次自有下载与 GPU 测试服务已停止，持久化数据和退出容器保留；没有启动 manager 或任何机器人轮询。
