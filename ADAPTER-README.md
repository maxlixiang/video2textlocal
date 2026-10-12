# Windows 抖音下载适配器

本实现位于独立新项目。仅抖音下载可交给 Windows；Telegram、唯一 SQLite 写入调度、GPU 和 DeepSeek 保留在 Docker。默认关闭，Windows 工作进程手动前台运行，不注册服务或计划任务。本轮没有启动生产机器人。实际结果见 [ADAPTER-TEST-REPORT.md](ADAPTER-TEST-REPORT.md)。

## 架构与协议

`v2t/manager.py` 在事件循环中运行 `adapter_broker.Broker`，唯一写入任务数据库。8082 控制线程只将请求交给该事件循环；异步等待下载时释放事件循环，不阻塞领取、心跳、完成通知。网络请求、块写入、哈希和解码在其他线程或进程。`adapter_coordinator.py` 是独立测试协调器，不能与真实 manager 同时持有同一个数据库锁。

下载服务 `adapter_gateway.py` 提供 mTLS 接口，Windows 主动领取，按 4 MiB 分块上传。网关只写任务目录和收据，不写 SQLite。网关与 manager 通过 Docker 内部网络和独立认证密钥通信。Windows 证书只获得指定 worker 身份，无该内部密钥、Telegram Token 或 DeepSeek 密钥。非测试模式没有创建测试任务的接口。

Windows 父进程独立心跳线程，浏览器、下载缓冲和本地解码在受 Windows Job Object 约束的子进程树中。固定匿名 Playwright 路线，不加载登录状态。领取后一次解析，最多四跳受限 CDN 重定向；块传输最多重试两次。验证码明确失败，无自动绕过或无限解析重试。

## 准备

Docker 使用基础 Compose 加显式 `compose.adapter.yaml` 覆盖文件。基础 Compose 没有适配器监听端口；覆盖文件仅发布 `127.0.0.1:18765`，不绑定局域网或公网。Windows 与 WSL 同宿主的 Docker Desktop 回环通信已实测；另一台 Windows 不在此次范围，需要另行设计网络与认证。

已验证依赖锁见 `requirements-windows.lock`；准备独立环境时使用该锁安装，并安装对应完整 Chromium。Windows 需要 Python、**Playwright 1.58.0 / 对应完整 Chromium 145.0.7632.6**、FFmpeg 和 FFprobe。实测使用已有 Windows Python 3.10.0 和 FFmpeg 7.0；未在原项目安装或修改依赖。正式使用建议在独立路径准备环境，只安装缺少的依赖，不借用原项目虚拟环境；本轮没有替用户安装全局环境。

复制 `windows-worker.example.json` 到专用配置路径，填写实际工具和证书路径、独立 spool。示例没有密钥。若该出口确实使用 fake-IP DNS，需在专用配置明确设置 `allow_fake_ip_dns=true` 才允许 CDN 假地址检查；这不改变 DNS/代理，也不能证明上游网络已隔离或修复。

使用专用 CA 签发 serverAuth（SAN 包含 localhost/127.0.0.1）和 clientAuth 证书。Docker 凭据目录包含 `ca.pem`、`server.pem`、`server.key`、`internal.key` 和 `workers.json`；后者格式是客户端 DER 证书 SHA256 指纹到稳定 worker ID 的映射。Windows 仅持有 CA 公钥、自己的证书/私钥。CA 私钥保管在其他专用位置，不必挂入容器，不添加到系统信任库。

`build_tools/adapter_pki.py --directory <不存在的独立目录>` 只生成测试 PKI：叶证书两天、CA 七天，并包含故障测试身份。不要作为长期证书发行方案。已存在目录会拒绝覆盖。给 Windows 专用私钥设置仅工作账号可读的 NTFS ACL；本轮不改变系统用户权限。

## 手动启动和停止

先完成 `.env.test` 的独立测试机器人配置：`BOT_PURPOSE=test`、`TELEGRAM_BOT_TOKEN`、`EXPECTED_TEST_BOT_ID`、`ALLOWED_USER_IDS`。原稿不需要 DeepSeek 密钥；整理验收另需 `DEEPSEEK_API_KEY`，并核实该账号可用的 `DEEPSEEK_MODEL`。启动前测试机器人 getMe ID 必须相符，不能使用生产 Token。

在新项目的 WSL 终端，明确设置专用凭据目录和开关后再启动：

```bash
export ADAPTER_CREDENTIALS_DIR=/absolute/path/to/dedicated-credentials
export WINDOWS_ADAPTER_ENABLED=1
docker compose --env-file .env.test -f compose.yaml -f compose.adapter.yaml --profile bot up -d
```

在 Windows PowerShell **手动前台**启动；下列 UNC 仅是本机已验证路径，可替换成独立源码副本，不能指向原项目：

```powershell
& 'C:\Users\justd\AppData\Local\Programs\Python\Python310\python.exe' '\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text\windows_worker.py' --config 'C:\Video2TextAdapterPrivate\worker.json'
```

`--max-jobs 1` 可限制为单个任务；默认连续领取，每次空队列等待一秒。网络/认证不可用退出并保留 journal，修复后手动重启。按 Ctrl+C 停止父进程，Job Object 关闭终止本次子进程树。Docker 停止只使用同样的环境及文件列表执行 `stop manager download gpu`；不要删除卷、批量清理或覆盖旧部署。

已有固定媒体验收使用 `compose.adapter-test.yaml`，独立数据库/媒体/结果卷，无 Telegram、GPU 或 DeepSeek 常驻服务。该文件默认有故障测试的短租约和解码延迟，**不是正常部署文件**。

## 期限、恢复与额度

排队默认 300 秒，从最新入队时间计；真实 manager 若等待超过十秒且没有近期 Windows worker 领取记录，会提前明确报 `adapter_unavailable`。领取才开始 600 秒执行期限；45 秒租约用 15 秒心跳续期，但不能延长执行硬期限。主服务与工作进程更改租约时要同步配置。

上传期间，4 MiB 块哈希、确认偏移和任务 generation 持久化；中断后重新领取同一未过期任务，从服务端确认偏移继续。重复确认幂等。租约过期旧 generation 无权提交；用户重试建立新 generation。Windows 已完整、输入 URL 哈希和媒体哈希一致时可复用媒体，不重新在线解析。

**上传完整并通过 SHA 校验、manager 接纳后**进入服务端 owned `validating`，此时 Windows 断线或客户端证书过期不撤销验收。默认独立 180 秒验收期限，Docker 重启从收据继续全音轨解码。期限内成功收据可在恢复后补报；验收超过期限明确失败。Windows 重启发现 validating/complete 时只等待或取状态，不重下载。

默认 Windows spool 总额度 4 GiB、磁盘最低剩余 2 GiB；领取预留 500 MiB 媒体和 256 MiB 浏览器临时文件。Linux media 总额度 8 GiB、最低剩余 2 GiB；提交预留媒体及最长单声道 16kHz PCM 音轨。保留的成功/失败文件都计入目录额度，运行期间继续检查 Windows 余额。结果与数据库使用独立持久化卷，模型使用已有 Linux 模型卷。目录额度不是操作系统硬配额，外部写入和不同卷布局仍可能影响剩余空间。

无自动批量清理。额度耗尽返回 `adapter_quota`，空间不足返回 `disk_full`；由用户检查保留目录，手动处理后重试相应任务。

## 证书更新与故障排查

客户端证书距到期不足十五分钟不领取新任务；过期证书握手拒绝。先在 workers.json 同时允许新旧指纹映射同一 worker ID，再原子替换专用证书/私钥文件，完成后移除旧指纹；稳定 ID 保留未过期租约。每次新连接重新读取证书，更新配置路径则需手动重启工作进程。

网关新连接重新读取服务端证书和 CA；服务端叶证书到期拒绝新连接。CA 轮换需有专用信任重叠窗口（CA bundle）、同步更新两侧文件与身份映射，然后验证再撤旧 CA，不修改全局系统信任。客户端叶证书续期恢复已实测，完整 CA/服务端轮换尚未实测。更新延迟造成未接纳上传租约过期时，用户重试新 generation，复用 Windows 完整缓存；已接纳媒体仍由 Docker 继续验收。

固定错误包括 `adapter_auth`、`adapter_unavailable`、`adapter_queue_expired`、`adapter_lease_expired`、`adapter_quota`、`disk_full`、`adapter_memory_limit`、`verification_required`、`target_mismatch`、`douyin_empty_response` 和阶段 timeout。认证与传输失败目前对 Windows 合并为认证/传输不可用，不能仅据此认定证书错误。

Job Object 默认限制子进程树 private commit 2 GiB。真实 54,281,244 字节样本峰值约 1.59 GiB，最多同时 11 个子进程；工作集采样合计约 1.54 GiB（共享页可能重复计数）。父进程及上传缓冲不属于这个子树预算，上传块最大 4 MiB。这条 Playwright APIRequestContext 下载路线缓冲整个响应，不能据文件长度推算安全内存。超预算明确失败，不自动扩大预算或改下载路线。更大文件的可行范围、长时间多任务内存和磁盘稳定性尚未验收。
