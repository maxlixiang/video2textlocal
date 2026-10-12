# Windows 抖音适配器实际测试报告

日期：2026-10-12。范围：独立新项目、手动 Windows 前台工作进程、专用 mTLS 回环通道、隔离 Docker 测试卷。无生产机器人、Windows 常驻服务或全局网络修改。原项目保护哈希见 `verification/adapter/final-integrity.json`。

结论：固定媒体交接与核心恢复验证通过；**一个公开抖音作品实际下载→交接→Docker FunASR GPU 原稿通过**。这不是长期稳定性验收，也不是完整 Telegram/DeepSeek 真实验收。

## 环境及证据

Windows Python 3.10.0、Playwright 1.58.0、完整 Chromium 145.0.7632.6、FFmpeg 7.0；Windows 依赖只读记录于 `requirements-windows.lock`。WSL2 Ubuntu 24.04、Docker Desktop WSL2 后端。RTX 4060 Ti 8188 MiB。专用测试栈仅 coordinator/download；GPU 使用一次性命名容器（停止后保留），模型卷来自独立新项目。

| 测试 | 结果 | 原始脱敏证据 |
|---|---|---|
| 固定 20 秒媒体、回环 mTLS、4 MiB 分块、Windows/Docker 全音轨解码、SHA 一致 | 通过 | `verification/adapter/wire-checks.json` |
| 无客户端证书、CA 有效但未授权身份 | 通过：拒绝 | 同上 |
| 过期租约、重复 finalize | 通过：旧租约拒绝，确认幂等 | 同上 |
| 上传和延迟解码期间独立心跳 | 通过：15 次心跳，短租约保持 | 同上 |
| Windows 上传中断、manager/download 双重重启、确认偏移恢复 | 通过：4,194,304 字节偏移保持，同 generation | `recovery-checks.json` |
| Windows 前台进程重启复用完整媒体 | 通过：同 SHA，不重新下载 | 同上 |
| 客户端新证书同 worker ID、未完成租约续接 | 通过 | 同上 |
| 过期客户端叶证书 | 通过：TLS 拒绝 | `late-checks.json` |
| 上传接纳后无 Windows 心跳，Docker 两侧重启仍完成 | 通过：28.08 秒等待超过 20 秒租约，同 SHA 完成 | `server-owned-check.json` |
| Windows 暂存额度、最低剩余空间 | 通过：`adapter_quota` / `disk_full` | `recovery-checks.json` |
| Linux 暂存额度、最低剩余空间、失败通知确认 | 通过 | `linux-adapter_quota.json` / `linux-disk_full.json` |
| Windows Job Object 实際预算注入 | 通过：64 MiB 预算下 512 MiB 分配未成功 | `late-checks.json` |
| 非阻塞唯一 SQLite 调度、期限、回调/输出/重试回归 | 通过：22 项离线测试，0.871 秒 | `final-unit.log` |
| 最终 manager / download 镜像构建 | 通过 | `build-manager-final.log` / `build-download-final.log` |
| 真实抖音匿名下载和 Docker 校验 | 通过：一个独立作品，一次修复后成功 | `real-windows.json` |
| 对交接音轨实际 Docker FunASR GPU 原稿 | 通过：130 段 | `real-funasr.json` / `real-funasr.log` |
| 独立测试机器人与 DeepSeek 实际发送/整理 | 尚未验证：缺配置 | `credential-readiness.json` |
| 服务端证书/完整 CA 轮换恢复、长期重复多作品、大文件预算范围 | 尚未验证 | 不作通过声明 |

表中省略目录的证据均位于 `verification/adapter/`，不含 Cookie 值、签名查询参数或密钥。测试用私钥与 Windows 私有配置不属于交付示例；没有输出秘密内容。

## 真实作品与 GPU

目标作品 ID `7695089785269996809`，用户提供 EP07 短链。任务 `73aff0b08c0b45e7b2b6f8a51d676316`。独立作品数 **1**，开发期间尝试 **3** 次，前两次失败，修复后一次成功；没有重复原来的整组四环境测试。

失败证据为 `real-windows-first-failed.json` / `real-windows-second-failed.json`。前两次发生在媒体请求前；定位到新工具验证码读取在页面导航期间直接 evaluate 抛错。恢复 Windows B 已验证的容错读取后成功。失败不能归因于抖音风控或出口变化，两个失败摘要未保存完整 SDK 异常文本，避免包含敏感地址。

成功运行全新匿名上下文，无登录状态或历史 Cookie；匿名 Cookie 仅记录数量 33。目标/解析作品 ID 一致，媒体 54,281,244 字节，时长约 356.73 秒，SHA256 `61ae344db7b9a97b9269cc8225196b6a10a8157dfaee2acb8afd32cf6578c7f3`。Windows 完整音轨解码和 Docker SHA、FFprobe、完整音轨解码均通过。

FunASR 1.2.7、Torch/Torchaudio 2.5.1+cu121；SeACo Paraformer、FSMN VAD、标点模型均 revision v2.0.4。ASR/VAD/标点均实测 cuda + float32，保留配置热词；未运行第二套 ASR。识别调用约 28.08 秒，130 个片段，UTF-8 原稿含时间戳。原稿文件：`verification/adapter/73aff0b08c0b45e7b2b6f8a51d676316_原稿.md`，未经过 DeepSeek。

GPU PyTorch 峰值分配 2,389,655,040 字节；整卡使用基线 1777 MiB、峰值 4194 MiB、子进程退出后回到 1777 MiB。整卡数值包含其他进程，不能全部归属于本任务。模型锁哈希及实际组件设备、精度完整记录于 real-funasr.json。

## 内存预算的实际含义

成功媒体下载：子进程树 private commit 采样峰值 1,709,793,280 字节（约 1.59 GiB），合计工作集峰值 1,649,225,728 字节（共享页可能重复计数），实际内核预算 2,147,483,648 字节；最多同时 11 个子进程、累计 15 个。测量覆盖浏览器子树，不包含心跳/上传父进程。

预算故障注入中，512 MiB 分配请求失败，成功标记未产生，采样 private commit 约 11.6 MB。Windows 内核峰值计数仍记录约 555 MB 的失败尝试；**不能把该计数当成获准分配的实际 RAM，也不能据此认为预算失效**。已核对内核 Job Memory Limit 标志和配置预算。实际安全边界来自内核约束与分配拒绝证据，不是 Content-Length。

保留 Playwright APIRequestContext 全响应缓冲路线意味着 54 MB 媒体就可能使用约 1.59 GiB。默认 500 MiB 文件上限并未获得相应最大文件成功证明；更大媒体会可能报预算限制。没有自动上调预算、CPU/云端回退或偷偷改变解析运输路线。

## 仍未验收与操作边界

此前 Windows 3/3 下载说明 Windows 路线具备可行性，不代表稳定性通过；Windows/Linux 同详情 GET 的零正文差异仍缺上游路由证据，未认定 Linux 指纹或 IP 风控。此次实施不改变该判断。

`.env.test` 尚不存在。真实 Telegram 验收缺 `BOT_PURPOSE=test`、独立 `TELEGRAM_BOT_TOKEN`、对应 `EXPECTED_TEST_BOT_ID`、`ALLOWED_USER_IDS`。真实整理另缺 `DEEPSEEK_API_KEY`，需确认账号可用模型并配置 `DEEPSEEK_MODEL`；示例模型名未获真实调用验证。原稿逻辑无需 DeepSeek 密钥已离线测试，真实机器人发送尚未测试。

实现与测试过程中修复了页面导航容错和失败 ACK 被错误当作失败响应的问题，对应离线回归与 Linux 故障测试已通过。本轮没有再次大量请求平台，也没有更改原项目、旧部署、全局网络或驱动。最终专用 coordinator/download 已停止，卷、证据和媒体保留，无 Windows 工作进程常驻。

## 后续新增真实 Telegram 原稿验收

新链接 `3RnVIQ3F_aY` 已完成 Windows 下载→Docker FunASR→测试机器人真实发送，113 个片段。详见 [本轮报告](verification/douyin-telegram-20261012/REPORT.md)。用户已在 `.env` 填写独立配置并通过 getMe 身份核验；此前缺配置记录属于历史状态。此次未启动长轮询或实际点击按钮，也未调用 DeepSeek；这些真实验收仍待完成。
