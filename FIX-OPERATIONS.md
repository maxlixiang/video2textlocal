## 2026-10-14 Windows 联动更新

已启用当前用户 Docker Desktop 联动任务，Windows worker 现由管理程序自动启动/停止，不再默认要求手动前台启动。操作及验证边界见 [WINDOWS-DOCKER-FOLLOWER.md](WINDOWS-DOCKER-FOLLOWER.md)。本文件此前的手动启动说明仅用于禁用联动后的维护，不能同时启动两个 worker。

# 修复版操作与维护

本轮独立项目为 `/home/codex/workspace/telegram-video2text`。原 Video2Text1、旧机器人和全局网络没有修改。日常仍是专用测试机器人；同一个 Token 只能有一个 manager 轮询进程。

## 启动和停止

最终验收使用 `compose.yaml`、`compose.adapter.yaml`、`compose.final.yaml`、`compose.egress.yaml`，不使用开发源码挂载。以下环境变量只有非敏感选择项，真实凭据从本地 `.env` 读取。

```bash
cd /home/codex/workspace/telegram-video2text
export BOT_ENV_FILE=.env
export ADAPTER_CREDENTIALS_DIR=/home/codex/workspace/telegram-video2text/.adapter-pki
export WINDOWS_ADAPTER_ENABLED=1
# 本机实际 DNS 为受限 fake-IP；仅启用应用的既有白名单范围。
export ALLOW_FAKE_IP_DNS=1
sg docker -c 'docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot up -d --no-build'
sg docker -c 'docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot ps'
```

Windows worker 在 Windows 终端手动前台运行 `windows_worker.py --config <独立配置文件路径>`。当前配置位置的非敏感索引在 `verification/fixes/windows-location.json` 的 `real_config` 字段；不要输出配置全文。退出前台窗口、注销或重启后进程停止，需手动再次启动；没有注册服务/计划任务。先启动 Windows 再启动 Docker 可以等待连接，指数退避上限可配置，默认 30 秒。遇到认证失败或证书失效停止并提示，不能关闭 TLS 校验。进程不依赖 SSH；若由远程终端启动，终端结束可能影响它，应在本地 Windows 前台启动。

停止本轮 Docker 服务（保留容器与所有持久化数据）：

```bash
sg docker -c 'docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot stop'
```

再次 `up -d --no-build` 恢复。Docker 的 `unless-stopped` 仅在 Docker Desktop 已启动时有效；不保证 Windows 开机自动启动 Desktop。没有修改系统开机设置。

## 证书到期和续期

这是专用测试 CA，不是系统信任根。当前 CA 很快到期，叶证书短期有效：先检查公开有效期，再续期；工具拒绝超过 CA 剩余有效期或超过 7 天的叶证书。不能用长期叶证书掩盖 CA 到期。

```bash
python3 build_tools/adapter_certificate_status.py --directory .adapter-pki
python3 build_tools/renew_adapter_certificates.py --directory .adapter-pki --days 2 --activate-server
```

工具生成新代次目录、保留稳定 worker 身份，并原子切换服务端证书对。旧指纹保留以支持短暂交叠；旧证书不应无限保留授权，交接完成且无未完成任务后，人工逐个撤销旧指纹。服务端每次连接读取新的证书对，无需重启。证书和私钥不得提交仓库、构建镜像或粘贴到命令行。

客户端把同代次 `worker.pem`、`worker.key` 及公开 `ca.pem` 复制到独立 Windows 凭据目录；随后原子更新其 `credential_manifest` 指向完整的新证书对。每次连接读取 manifest，可在活动任务上传时换证，仍使用相同 worker 身份和 generation。本轮实际更新脚本和回执见 `verification/fixes/protocol_recovery.py`、`protocol_finish.py`。不能只更换证书而继续引用旧私钥。临期 24 小时警告；距到期不足领取安全余量（默认 15 分钟）拒绝领取新任务。

CA 更新需要独立安排：暂停领取、等待活动上传/验收完成，建立新专用 CA、服务端和客户端证书，更新两侧专用 CA 文件及 workers 身份映射，再重新连接验证。不要添加全局信任根。CA 更新尚未实测；不能把已通过的同 CA 叶证书续期当作 CA 轮换通过。

## 恢复规则

Windows 短暂网络错误继续等待，有上限的退避间隔，不是无限快速重试。下载媒体完成后有 hash/journal，可在有效租约内继续上传；Docker 校验阶段由服务端验收期限管理，不要求上传租约持续延长。已提交的完整媒体可恢复验收。过期 generation 拒绝旧确认，用户在 Telegram 点“重试未完成阶段”建立新执行代次；完整 Windows 媒体仍可复用。排队期限默认 300 秒，领取后的执行期限默认 600 秒，租约默认 45 秒，验收期限默认 180 秒。

任务排队/状态/心跳由 manager 唯一 SQLite 调度；等待 Windows 下载使用异步等待，不占住事件循环。每条 Telegram update 先持久化脱敏 inbox，再处理并持久化任务；结束或有界失败后原子推进 offset。待处理 inbox 在重启后先恢复。永久回复失败隔离后继续下一条。消息已发但响应/落库丢失仍有不确定投递窗口，不承诺 exactly-once。单人版串行执行任务，排队时仍可接收消息和心跳。

整理失败可点阶段重试，缓存校验通过时不重复下载或 GPU 识别、不重发已确认原稿。模型/热词/识别参数改变会使原稿缓存失效；提示词/整理参数改变只使整理缓存失效。/status 只显示自己的任务，也可找回待选择按钮。

## 空间与人工维护

默认 Docker 媒体额度 8 GiB、结果额度 2 GiB；下载前预留最大媒体和音轨空间，媒体磁盘至少保留 2 GiB，结果至少 512 MiB，数据库至少 256 MiB。Windows spool 默认 4 GiB、最低余量 2 GiB；预算应结合视频大小和保留任务调整。当前独立 Windows 实测配置下载子进程树内存预算 6 GiB，可配置，不能据此保证 500 MB/2 GB 文件一定成功。Playwright 下载响应会完整缓冲，文件尺寸并不等于进程峰值。

Docker 日志每服务最多 3×10 MB。数据库、Windows spool 和诊断材料不会自动删，数据库没有总容量上限，诊断目录不受运行结果额度管理，需人工检查。Windows 和 Docker 各留一份媒体，会同时增长，不能假定已发送后自动回收。

人工查看 Docker 命名卷位置与占用、Windows 独立 spool 占用；只在任务完成、无需恢复且已备份后，逐一选择明确文件处理。禁止批量删除、prune、down -v。不要删除运行中的 SQLite/WAL 文件。额度不足拒绝新工作并返回固定错误；媒体/结果保护的余量无法阻止其他程序耗尽整个磁盘。

## 网络和用户提示

抖音适配器默认关闭；关闭明确提示未启用，打开但离线明确提示离线并提供阶段重试。无默认 Linux 回退，Linux 诊断只能显式启用 `DOUYIN_LINUX_DIAGNOSTIC=1`。交接仅宿主回环 127.0.0.1:18765，专用 mTLS；其他 HTTP 接口只在内部 Docker 网络，不发布宿主端口。

Windows 浏览器的导航、跳转、子资源和 WebSocket 检查平台/CDN 域名白名单及解析地址，拒绝私网；仅明确打开既有受限 fake-IP 策略时接受白名单域的 198.18/15。这不证明上游路径一致，也不彻底消除 DNS 检查与连接间的重绑定窗口。没有修改全局代理/DNS。

抖音 Windows 小样本成功仅证明当前出口可行，不是稳定性验收。X 依赖 fxtwitter，指定 /video/2 会选择第 2 个媒体而不是默默下载第 1 个。GPU 无 CPU/云端静默回退。Telegram 云端媒体发送限制 50 MB，与本地转写媒体限额不同。


最终日常配置不要附加 `compose.polish-failure.yaml`（仅本轮受控缺密钥测试）；诊断与候选 Compose 也不用于日常启动。Windows 下载器主程序直接位于项目根 `windows_worker.py`，无需使用 `verification/fixes/run_windows_foreground.py` 包装脚本；运行配置与凭据在 Windows 独立目录。当前源码从 WSL UNC 读取，因此先确保 WSL 可用，再启动 Windows worker；“先 Windows、后 Docker”的已测场景指 WSL 已在运行而 Docker 服务未启动。真实 Windows 系统重启/睡眠尚未由用户执行。

当前默认领取安全余量 15 分钟与执行 600 秒＋验收 180 秒匹配；若调长任务期限，应同步调大 Windows `certificate_claim_margin_seconds`。当前真实测试配置 `reconnect_max_seconds=4` 用于快速观察，生产默认 30 秒；可在停掉单个前台 worker 后修改独立配置并重启，不修改全局网络。


## 当前 Windows 前台的明确操作

在 Windows PowerShell 中运行（不要同时启动第二个 worker）：

```powershell
& "C:\Users\justd\AppData\Local\Programs\Python\Python310\python.exe" "\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text\windows_worker.py" --config "C:\Users\justd\AppData\Local\TelegramVideo2TextAdapter\fixes-20261013-002320\real.json"
```

停止用 Ctrl+C，最好等当前任务完成后停止；再执行相同命令恢复。当前测试前台进程仍在运行，另开窗口前需先停本轮 worker，避免 spool 锁冲突。

执行 Linux 续期工具后，在 Windows PowerShell 更新专用凭据；下面只处理文件路径，不包含密钥值。UTF-8 无 BOM、同目录 File.Replace 保持 manifest 原子替换：

```powershell
$workerConfig = "C:\Users\justd\AppData\Local\TelegramVideo2TextAdapter\fixes-20261013-002320\real.json"
$pki = "\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text\.adapter-pki"
$c = Get-Content -LiteralPath $workerConfig -Encoding UTF8 | ConvertFrom-Json
$g = (Get-Content -LiteralPath (Join-Path $pki "active-generation.json") -Encoding UTF8 | ConvertFrom-Json).generation
$d = Join-Path (Split-Path $c.credential_manifest) $g
New-Item -ItemType Directory -Force -Path $d | Out-Null
Copy-Item -LiteralPath (Join-Path $pki "renewals/$g/worker.pem") -Destination (Join-Path $d "worker.pem")
Copy-Item -LiteralPath (Join-Path $pki "renewals/$g/worker.key") -Destination (Join-Path $d "worker.key")
Copy-Item -LiteralPath (Join-Path $pki "ca.pem") -Destination (Join-Path $d "ca.pem")
$value = @{cert=(Join-Path $d "worker.pem"); key=(Join-Path $d "worker.key"); ca=(Join-Path $d "ca.pem")} | ConvertTo-Json
$tmp = $c.credential_manifest + ".new"
[System.IO.File]::WriteAllText($tmp, $value, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::Replace($tmp, $c.credential_manifest, $null)
```

上述操作不注册服务、不写系统信任根、不改 Windows 网络。生成代次目录已存在时，只能用于同一代次文件；不要混配不同代次证书与私钥。当前短期 CA 到期前需安排独立 CA 更新；该项尚未实测。

空间检查也会在目录权限/磁盘查询失败时停止工作；遇到 disk_full 时除剩余空间外，也检查独立暂存目录是否可读。


Windows 重启后曾实际出现“容器运行但 WSL 配置/证书挂载缺失，manager 反复重启”。仅打开 Docker Desktop 并不总能完整恢复，现象与保留数据卷的恢复命令见 [REBOOT-RECOVERY.md](REBOOT-RECOVERY.md)。当前 healthcheck 仅检查 HTTP 存活。


后续媒体保留更新：当前 `compose.final.yaml` 使用 `retention` 镜像，已完成任务的媒体/音频保留 72 小时后逐文件清理；旧文档“没有自动清理”描述的是此前修复验收状态。当前策略与用户授权范围见 [MEDIA-RETENTION.md](MEDIA-RETENTION.md)。启动停止仍使用相同四个 Compose，不删除卷。

## 2026-10-13 重启与专用证书更新

日常启动请优先遵循 [REBOOT-RECOVERY.md](REBOOT-RECOVERY.md)，替代先前直接 bind 整个凭据目录的命令。运行配置与各角色凭据使用 Docker 管理的独立持久卷；原数据卷保留。证书维护与 CA 轮换见 [CERTIFICATE-LIFECYCLE.md](CERTIFICATE-LIFECYCLE.md)。Windows worker 仍需手动前台启动，未注册服务或计划任务。
