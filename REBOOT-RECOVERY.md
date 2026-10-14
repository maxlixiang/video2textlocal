## 2026-10-14 Windows 联动更新

已启用当前用户 Docker Desktop 联动任务，Windows worker 现由管理程序自动启动/停止，不再默认要求手动前台启动。操作及验证边界见 [WINDOWS-DOCKER-FOLLOWER.md](WINDOWS-DOCKER-FOLLOWER.md)。本文件此前的手动启动说明仅用于禁用联动后的维护，不能同时启动两个 worker。

# Windows 重启恢复与启动顺序

## 已有故障的证据与结论

2026-10-13 首次 Windows 重启后，GPU/download 显示 healthy，manager 重启循环。宿主 hotwords.txt 与证书存在，但对应容器只读 bind 目录变空；GPU `/configuration` 返回 invalid_input，重新创建本项目容器后文件恢复。这证明故障来自当时的配置/证书挂载可见性，不是凭据被删除。Docker Desktop 内部挂载桥接与 WSL 初始化的具体触发顺序尚未隔离，不能认定已证明某个 Desktop bug。

旧健康检查仅确认 HTTP 存活，漏报配置缺失。Compose 的 depends_on 只在 Compose 启动时排序；Docker Engine 的容器重启策略不会重新执行该排序。

## 本轮修复

日常运行不再把 WSL 的 config/证书目录 bind 到在线容器。配置先经 `build_tools/prepare_runtime.py` 检查并同步到独立 Docker 管理卷；manager/GPU 只读同一配置卷。各角色证书也采用独立运行卷。签发目录不挂载在线服务。因此容器随 Engine 重启时，无需等 WSL bind 可见才能读取已保存运行文件。

启动工具检查 bot 配置文件、Docker 可用、UTF-8 配置、服务器证书/私钥匹配、信任链、worker 映射和有效期，失败不启动服务。请使用单一启动工具，不能忽略 preflight 错误后另行启动 Compose。

GPU readiness 检查配置、模型锁与识别参数、可见 GPU 和磁盘剩余；download 检查磁盘与启用时的 mTLS 材料。失败返回 HTTP 503。此检查**不是实际 GPU 推理**，也不保证每个模型文件内容完好。manager 在开始 Telegram 长轮询前等待依赖就绪并校验识别配置；运行中每 10 秒更新健康标记，过期标记不视为健康。Windows worker 离线仍通过明确的任务失败/可重试提示处理；健康不承诺 Windows 在线或平台网络畅通。

## 日常启动（现有同一项目及原数据卷）

1. 打开 Docker Desktop，确认引擎运行。
2. 在 Ubuntu/WSL 终端运行：

```bash
cd /home/codex/workspace/telegram-video2text
sg docker -c './build_tools/start_local.sh'
```

脚本使用 `.env`、`compose.yaml + compose.adapter.yaml + compose.final.yaml + compose.egress.yaml`，项目名 `v2t-live-fixes`，不会删除或替换媒体、结果、数据库和模型卷，也不会重新构建镜像。运行卷已经初始化时，Windows 重启后仅打开 Docker Desktop，应能自动恢复三个 Linux 服务；真实重启仍需本轮验收，不能只凭 restart 策略写为通过。

3. Windows worker 仍需手动前台启动。先在 PowerShell 打开 WSL：

```powershell
wsl.exe -d Ubuntu-24.04 -- true
& '\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text\build_tools\start_windows_worker.ps1' -Config 'C:\Users\justd\AppData\Local\TelegramVideo2TextAdapter\fixes-20261013-002320\real.json'
```

该脚本不注册服务或计划任务，会拒绝同配置的第二个 worker。若系统执行策略禁止脚本，可直接运行以下命令（不修改全局执行策略，先确认没有已运行 worker）：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe" '\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text\windows_worker.py' --config 'C:\Users\justd\AppData\Local\TelegramVideo2TextAdapter\fixes-20261013-002320\real.json'
```

关闭该窗口、退出 Windows 登录或重启都会结束 worker。Linux 服务健康不意味着 worker 已启动。源代码仍从 WSL UNC 加载，所以必须启动 Ubuntu；运行配置不依赖 verification 中的路径索引文件，独立 Windows JSON 配置/凭据/spool 保留在 AppData。

## 查看、停止、恢复

```bash
sg docker -c 'docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot ps'
python3 build_tools/runtime_certificate_status.py
```

停止本项目时先在 Windows worker 前台按 Ctrl+C，再用相同 Compose 文件执行 `stop`；下次使用启动脚本，不能用删除卷的命令。不要同时启动旧测试 manager；本机器人只有一个长轮询进程。

启动检查失败：检查真实宿主配置是否存在，使用证书生命周期文档恢复有效材料，再重新运行启动脚本。新的运行卷不会随宿主编辑自动变化；改热词/续证后必须运行 prepare/start。没有为本次修复修改 Desktop、WSL、Windows 自启动、驱动、代理或 DNS。

## 实测状态

- 已通过：57 项回归；实际缺配置 health 返回 HTTP 503；持久配置/角色卷部署后全部服务 healthy；真实 CA 轮换中固定媒体断点恢复及双侧解码。
- 原数据库、媒体、结果和模型卷名称不变；见 `verification/recovery/runtime-audit.json`。
- 真实 Windows 重启验收：待用户手动重启、打开 Desktop、确认自动恢复与启动 worker，并通过 Telegram 按钮完成原稿任务后记录。不得以容器 restart 代替 Windows 重启验收。
