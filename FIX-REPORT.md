# FIX-REPORT：集中修复和真实交互验收

日期：2026-10-13（北京时间）。结论：**本轮三平台两稿流程已完成真实 Telegram 用户交互验收，适合目前单人、有人维护的自用。尚不属于无人值守或全面稳定性验收。**

用户实际发送链接、点击按钮、集中重试，并确认收到 5 份整理稿，抽查“没什么内容错误”。这是一次用户抽查反馈，不是自动证明没有遗漏、新增事实或全部语音准确。程序只核对阶段、文件、响应完整性和发送回执。

## 1. 交付版本与实际运行

基线提交：`a8481603df96bb137601c256f0e63da6aeea1506`。本报告随修复源码提交仓库；实际运行版本按以下冻结摘要和镜像 ID 核对。最终冻结内容摘要：

`0d29644035af11c67326bfaa620c6e81fb2346beaf5905588d034f2835182b36`

逐文件摘要在 `verification/fixes/source-manifest.json`，覆盖运行源码、镜像输入、运维工具、测试及最终 Compose；最后完整性检查确认没有再改这些文件。文档更新不改变运行代码。实际镜像 ID：

| 服务 | 最终镜像 ID |
|---|---|
| manager | `sha256:d64053a0bf39c73d7f55173ccaaa15518e1f46660672e5b79bc88c1e971a18b5` |
| download | `sha256:f0b58249cac4d4e5c928f5c8da1e6be761d3a71619d33e7ac06bd78e5597ff2d` |
| gpu | `sha256:b8d6ed3f7807a90bfe950544fcea57efbbcc30736dd22a780c2f0bfce043355f` |

日常测试栈：`v2t-live-fixes`，使用 `compose.yaml + compose.adapter.yaml + compose.final.yaml + compose.egress.yaml`。镜像标签 `fixes-final`；没有开发源码挂载。正常 config、凭据只读挂载，数据使用独立卷，模型沿用已固定模型卷。实际 image/source/worker 摘要、挂载、回环端口和日志轮转：`verification/fixes/final-deployment.json`。

当前 **3 个日常测试容器运行，独立 Windows worker 前台运行**。只有这一个测试 Token 的轮询 manager。临时配置测试 GPU、固定媒体协议 coordinator/download 均已停止，容器、卷和证据保留；没有 prune、删除卷或批量清理。开轮没有旧日常容器在运行，本轮未停止旧部署。

Windows worker 使用独立新项目根的 `windows_worker.py`，没有调用桌面 Video2Text1 主程序。配置/凭据/spool 位于独立 Windows 目录，路径索引在 `verification/fixes/windows-location.json`，配置正文不进入报告。实际前台进程重载最终 worker；Windows 下载子进程也读取最终源码。没有注册服务、计划任务、修改开机设置。

## 2. 优先修复逐项结果

| 项目 | 修改、源码依据 | 验证与限制 |
|---|---|---|
| 单条 update 失败隔离 | `v2t/manager.py:297` 的 `ingest`、`:322` 的 `poll`；`core.py:Store.inbox_put/inbox_finish`。先落脱敏 inbox，再幂等持久化任务；成功/有界失败和 offset 在同一事务结束。永久回复失败不重放；临时错误最多 3 次，退避 1/2 秒。重启优先恢复 pending inbox。异常更新保存固定错误码。 | 最终 **45 项隔离回归通过**，包括永久 sendMessage 失败后下一链接/回调、重复 update 不增任务、第三次暂时重试成功、异常更新隔离；`unit-final.log`。Telegram 响应丢失仍有不确定投递窗口，不承诺 exactly-once。 |
| 配置与缓存一致 | `compose.yaml:13` 起统一热词路径、模型/revision、beam/VAD、FunASR batch；`service.py:Handler.do_GET/do_POST` 校验 manager/GPU 完整参数和模型锁；`worker.py:58` 使用实际配置推理；`core.py:167/172`、`manager.py:23` 区分权重配置与解码/热词缓存配置。 | 真实 Compose 自定义热词路径、beam=3、VAD=0：**FunASR/Whisper 实际 CUDA 推理通过**，分别 115/123 段；不一致模型在推理前拒绝。`compose-configuration.json`、`compose.configuration-check.yaml`。词表/模型/精度等缓存失效由回归覆盖，未下载另一套模型做额外在线验证。 |
| Windows 断连恢复 | `adapter_worker.py:Worker.run/execute`，`adapter_common.py:51`。网络/服务暂不可用用指数退避，上限默认 30 秒；认证/证书错误独立提示、停止，不关闭 TLS。活动任务保留 generation、hash、偏移和截止；心跳线程独立。 | Windows 先启动/Docker 后启动、空闲服务停止恢复、上传中断与 Docker 两侧重启实测通过；`protocol-recovery.json`。最终真实 worker 在 manager 镜像切换时继续等待并连接恢复。真实 Windows 系统睡眠/系统重启未执行。 |
| 证书生命周期 | `build_tools/renew_adapter_certificates.py:9`、`adapter_certificate_status.py`；`adapter_gateway.py:129` 每连接读取原子服务端证书对；客户端每连接读取原子凭据 manifest。保留稳定 worker 身份，短期叶证书，临期提醒、15 分钟领取余量。 | 最终镜像固定媒体实测双侧换证、4MiB 已确认偏移恢复、相同 generation、媒体不重新下载、两侧音轨校验；`final-certificate-recovery.json`。未授权/无客户端/过期证书及过期租约拒绝实测：`protocol-recovery.json`。CA 整体轮换尚未验证。 |
| 抖音路由明确 | `manager.py:96`：关闭时报“Windows 抖音下载适配器未启用”；启用但离线明确提示、保留阶段重试；默认没有 Linux 回退。诊断必须显式 `DOUYIN_LINUX_DIAGNOSTIC=1`。 | **用户真实按钮验证关闭、离线、连接恢复后三种状态**。同一个首轮任务恢复后原稿送达。`live-disabled.json`、`live-offline.json`、`live-final.json`。 |
| 磁盘与日志 | `storage.py:6/18`，`download.py:110/150/287`，`core.py:85/213/Store.create/enqueue`；数据库 admission 预留。`compose.yaml:34/63/88` 每服务日志 3×10MB。 | Windows 总额度/最低余量拒绝实测 `disk-checks.json`；Linux 空间保护与扫描错误受控回归。未真实填满磁盘，不宣称覆盖所有宿主 VHDX/外部进程耗尽空间情况。无自动删除。 |
| 浏览器私网限制 | `browser_policy.py:8/22`、`adapter_download.py:download`：导航/跳转/子资源/WebSocket 的域名和 DNS 地址校验，禁 service worker；只有明确开启的白名单 fake-IP 可用。 | 本地受控浏览器私网跳转、脚本私网请求被阻断，实际私网请求数 0；`browser_controlled.py`。限制后真实 Windows 公开视频下载成功。仍有 DNS 校验与连接之间的重绑定窗口，不把 fake-IP 放行当作上游网络已隔离。 |

## 3. 真实验收发现并完成的追加修复

1. **Whisper VAD 实际仍固定开启**：最终检查发现参数传播完成但调用遗漏，已改为读取实际配置；真实 VAD=0 推理重验通过。默认开启的旧输出不因此失效。
2. **X 混合附件索引**：提供的 `/video/2` 是图片后的视频，不是第二个视频。一次详情诊断 HTTP 200、7868 字节、1 图＋1 视频。`download.py:204` 的 `indexed_twitter_video` 现在按混合附件位置选，不能确定顺序时拒绝猜测。默认旧 fxtwitter MP4 路线保留；第三方失败明确报错。真实第 2 项下载/识别成功。
3. **本机受限 fake-IP 应用开关未传播**：第一次 X 请求被本地 URL 校验拦住，没有到第三方接口；补充显式 `compose.egress.yaml`，仅白名单域允许 198.18/15。没有修改全局代理、DNS、路由。第一次失败不作为第三方服务不可用的证据。
4. **浏览器清理异常覆盖成功获取**：任务 `38492995…` 写下 1,641,810 字节后 `browser.close` 抛错。`adapter_download.py:close_browser_resources` 保留主流程结果、记录清理异常类型，媒体仍须独立完整解码后提交。恢复真实下载通过。
5. **Chromium 临时目录消失导致 worker 退出**：Python3.10 rglob 迭代器碰到正在删除的浏览器目录，进程退出、后一任务租约过期。`adapter_common.py:22` 改为不跟随链接的扫描，只容忍消失，对权限/其他 I/O 错误明确报错；Linux 结果空间统计复用。回归和真实 worker 恢复下载通过。没有内存超限证据：失败进程峰值约 1.1GiB，预算 6GiB。证据 `worker-download-metadata.json`。

这些发现不是全部在第一版“通过”。早期镜像、故障及修复后版本分开记录。初轮镜像见 `initial-interaction-deployment.json`；最终清单见 `final-deployment.json`。最后追加只改空间扫描和浏览器清理/诊断字段；识别模型/参数、推理代码、提示词及缓存配置未再变化。YouTube/X 整理重试在最终镜像复用已校验原稿，不能表述为最终补丁后又重新下载/推理了一次；Windows 修复路径和最终镜像换证已实际重验。

## 4. 三平台真实交互验收表

全部行来自用户发送消息、真正 getUpdates 长轮询和用户按钮；不是脚本注入任务。每行代表 1 个独立作品；抖音共 2 个、YouTube 共 2 个、X 共 1 个。语言为实际识别结果，用户抽查反馈另记。

| 平台 / 公开样本 | 时长、语言 | 下载/完整音轨解码 / GPU | 原稿 / 实际 DeepSeek / 整理稿送达 | 任务证据 |
|---|---|---|---|---|
| 抖音 `AXDVruuIVAg` | 23.685s，zh | Windows 下载交接通过；用户按钮从默认 FunASR 切为 Whisper，cuda/float16，15 段 | 全通过，DeepSeek 1 块，finish_reason=stop | `384929951df047b593db226e6fe762af` |
| 抖音 `vphsfm0rpY0` | 50.109s，zh | Windows 下载交接通过；默认 FunASR，cuda/float32，35 段 | 全通过，DeepSeek 1 块，stop | `416509be54774f56a25dcad6576e764a` |
| YouTube `DGwRglnCTqs` | 178.461s，zh | Docker yt-dlp＋完整解码；Whisper cuda/float16，96 段 | 全通过，DeepSeek 3 块全部 stop | `bed3f1a0ad0c42719f315d38277fad18` |
| YouTube `G14CnqM70Cw` | 83.581s，en | Docker yt-dlp＋完整解码；Whisper cuda/float16，57 段 | 全通过，DeepSeek 1 块，stop | `4247e816ffcf4b62b22bff66c7ba6c02` |
| X `2109130078777118856/video/2` | 60.117s，en | Docker fxtwitter 指定混合附件第二项＋完整解码；Whisper cuda/float16，12 段 | 全通过，DeepSeek 1 块，stop；有识别文本，未沿用无语音样本 | `339b9b0d36a04eee8bb3aaae84c5c09a` |

共同证据：`verification/fixes/artifacts-final.json`（设备、精度、时长、块完整性、附件 hash、Telegram message_id，**没有正文**）、`live-final.json`（阶段和 inbox）、`output-format-checks.json`（UTF-8，原稿时间戳、整理稿时间戳范围为 0）。用户确认收到 5 份整理稿、抽查无明显内容错误。X/英语/中文的系统语言判断不代替完整听音核对。

真实视频模式补验：抖音 `AXDVruuIVAg`，任务 `a59343acbc224a9fbe0310b5b518fbe0`。用户收到视频，只有 download/sending_video 阶段，没有 GPU/DeepSeek。用户实际双击，Telegram 只送到 **1 个 video 回调**；1 个任务、1 次成功下载、1 次发送。**不能据此声称真实收到两个相同回调的服务端去重已验证**；该情况由受控回归覆盖。见 `live-button-checks.json`、`live-final.json`。

最终队列为空，pending inbox=0；首轮旧 X 诊断任务仍保留 failed，不伪造改成成功。

本轮共 11 个用户消息任务：初轮原稿/故障诊断、最终两稿、视频模式分别保留，不把同作品多任务算作独立作品。历史无语音 X 不计本轮语音验收。

## 5. 失败、恢复与并发验收

| 行为 | 分级与实际结果 | 证据 |
|---|---|---|
| 永久回复失败后后续消息继续 | **受控测试通过**，真实 Telegram 未故意封禁/破坏权限 | `unit-final.log`、`tests/test_fixes.py` |
| 缺 DeepSeek 密钥时原稿正常 | **真实交互通过**，临时覆盖运行进程密钥为空，原文件未改；两条 YT/X 原稿先送达，然后明确失败 | `live-before-retry.json`、`artifacts-before-retry.json` |
| 恢复后只重试整理、不重复原稿 | **真实交互通过**，用户点击重试；三任务下载/识别成功次数前后均 1→1，已确认原稿 message_id 不变 | `stage-retry-checks.json` |
| 同用户连续提交、按钮切换 | **真实通过**，5 条集中排队、串行完成；抖音按钮切到 Whisper 并实际推理。共 11 个不同消息去重键，pending inbox=0 | `live-button-checks.json`、`live-final.json` |
| 重复 update/回调、归属与白名单 | **受控通过**；用户双击视频也只执行一次，但服务端实际收到的回调仅 1 个；实际多用户竞争未验证 | `tests/test_core.py`、`test_fixes.py`、`live-button-checks.json` |
| manager/Docker 重启、Windows 下载等待不堵调度 | **实际通过**：队列保留恢复；本地固定媒体上传中断、两側 Docker 重启恢复同偏移；等待期间领取/心跳/数据库调度持续 | `protocol-recovery.json`，初轮/最终 `live-*.json` |
| Windows 下载进程退出恢复 | **实际通过**：本轮暴露退出故障，修复后前台重新启动、用户阶段重试完成；有效 journal 媒体/偏移支持继续 | `worker-download-metadata.json`、`artifacts-final.json` |
| 租约过期、上传完成后验收 | **固定媒体实测通过**。leased/uploading 要心跳＋执行截止；received/validating 按服务端验收期限恢复，原 generation 保持；过期旧心跳拒绝 | `protocol-recovery.json`、`final-certificate-recovery.json` |
| 双侧叶证书更新 | **最终镜像固定媒体实测通过**，相同 generation、4MiB 偏移、媒体 mtime 未变、两侧解码；日常 worker 共享原子 manifest 继续运行 | `final-certificate-recovery.json` |
| GPU OOM、DeepSeek 超时/限流、Telegram 发送失败/确认丢失 | **代码/受控覆盖部分，真实故障未验证**。没有故意耗尽 GPU、额度或真实投递响应；分块失败/截断、发送阶段复用由回归覆盖。不承诺严格 exactly-once | `worker.py:32`、`polish.py`、`telegram.py`、`tests/test_core.py` |
| Windows 系统睡眠/重启、CA 整体轮换、物理磁盘耗尽、500MB/2GB 媒体 | **未验证**。不以 worker 进程或 Docker 重启替代系统级验收；没有擅自执行系统变更 | 后续由用户安排 |

## 6. 运维、空间与安全边界

简明启动、停止、续期、恢复、人工维护命令在 **`FIX-OPERATIONS.md`**。当前启用 Windows 适配器，代码默认仍关闭；宿主只发布回环 `127.0.0.1:18765`，专用 mTLS；其他接口仅 Docker 内部网络。临时测试 18766 服务已停止。临时 `compose.polish-failure.yaml` 已移除，不用于日常运行。

Windows 下载子进程树实际内核内存预算 **6GiB**。最终 1.6MB/7.8MB 小样本峰值约 **1.10/1.20GiB**，最大活跃进程数量和内核限额记录在 artifacts/windows 字段；不靠 Content-Length 推测预算，也不保证 500MB/2GB 文件成功。GPU RTX 4060 Ti 8GiB，实际 CUDA/精度如上，全卡 nvidia-smi 峰值约 4049–4177MiB，含其他进程，不能当成单模型显存需求或大文件保证。每次 GPU 子进程结束释放引擎，不默认常驻两套大模型。

默认媒体额度 8GiB/最低余量 2GiB，结果 2GiB/最低余量 512MiB，数据库 admission 预留 256MiB；Windows spool 4GiB/最低余量 2GiB。模型/媒体/结果/数据库为独立卷或目录。Windows 和 Docker 各保留媒体，不自动回收；SQLite 与诊断材料未设总容量硬上限，需要人工维护。日志轮转每服务 3×10MB。保护为应用层 admission/写入检查，不是宿主硬配额，不能阻止其他程序耗尽磁盘。不得批量清理或删除运行中的 DB/WAL；无 prune/down -v。

当前叶证书到 **2026-10-15 01:01:22 北京时间**，CA 到 **2026-10-19 16:48:28 北京时间**。这是短期测试 PKI，需按说明续期；不能据此宣称长期无人维护可用。公开有效期在 `certificate-status.json`。专用凭据目录整体只读挂载，尚未按容器角色进一步精简其可读文件范围；私钥没有进入仓库或镜像构建上下文，但本机应保护该目录及 Docker 管理权限。

Windows worker 手动前台；关闭窗口、注销、重启后需手动启动。Docker unless-stopped 只在 Docker Desktop 已启动时生效，没有配置主机开机启动。源码经 WSL UNC 读取，WSL 必须可用；主程序不依赖诊断包装脚本，也不要求保持 SSH。当前测试由本轮前台会话启动，日常使用请在 Windows 本地终端直接运行。

应用 fake-IP 兼容覆盖保留，是因为真实详情/CDN DNS 在本出口为 198.18/15；它只允许已有域名白名单，不代表出口一致、Linux 指纹或平台风控原因已被隔离。抖音小样本成功是当前出口可行性与本轮流程证据，不是稳定性承诺。X 继续依赖 fxtwitter。

## 7. 完整性与剩余验收

`delivery-integrity.json`：原 `dy.py`、`video_to_text.py`、`funasr_asr.py`、`polish_article.py` 的 hash 仍与保护基线相同；34 个 Python 文件 AST/UTF-8 回读通过；最终冻结源码未再变；发布输入和操作说明的凭据模式检查没有命中。该扫描不是所有宿主文件不存在敏感信息的证明。报告/证据均不包含 Token、Key、私钥、Cookie 值、签名 URL 或稿件正文。

剩余：用户安排真实 Windows 睡眠/重启；CA 轮换；真实发送不确定窗口、API 超时/429（可先受控测试）；更大媒体与长期运行；更多抖音出口样本；服务端实际接收两次相同按钮回调的在线测试；多人任务。当前串行和人工维护的限制已明确，因此适合单人受控日常自用，不能当作全部可靠性验证完成。

关键材料：`README.md`、`FIX-OPERATIONS.md`、本报告、`v2t/manager.py`、`core.py`、`service.py`、`worker.py`、`adapter_worker.py`、`adapter_broker.py`、`adapter_gateway.py`、`adapter_download.py`、`browser_policy.py`、`storage.py`、`download.py`、`polish.py`、`telegram.py`、最终四个 Compose、证书工具和 `tests/test_fixes.py`。交接应排除 `.env*` 实值、PKI 私有目录、spool、媒体、模型、数据库、私人结果；本轮脱敏 JSON 可按报告所列文件单独给审阅者，不整份打包 verification。


发布补充：`verification/fixes/` 所列证据是本机路径，没有整份上传到公开仓库。用户随后手动清理了已停止容器和构建缓存；脱敏报告及任务卷未由本轮上传操作删除。用户报告 Windows 重启后，发现配置/证书挂载缺失，重建容器后恢复 manager 与 Windows worker 连接；详见 REBOOT-RECOVERY.md，不将自动挂载恢复记为通过。

## 后续重启与 CA 修复

2026-10-13 的运行版本与凭据挂载已经更新，请同时阅读 [RECOVERY-FIX-REPORT.md](RECOVERY-FIX-REPORT.md)。旧镜像 ID、证书有效期和 bind 挂载描述作为历史记录保留，不代表当前部署。
