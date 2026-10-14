# Windows 抖音下载与 Docker Desktop 联动

2026-10-14 已安装并启用当前用户任务 `Video2TextLocal-DockerFollower`。这是用户登录后的低权限任务，不是 Windows 系统服务，不保存登录密码，不修改 Docker Desktop 的自启动设置。只管理新项目的 Windows 下载 worker。

## 日常行为

- 登录 Windows 后，管理程序在后台等待 Docker Desktop。Docker Desktop 的桌面/后台进程出现且专用 mTLS 下载接口可用后，启动一个 worker。
- 真正退出 Docker Desktop 后，约 5～15 秒内关闭所管理的 worker 及其下载子进程。管理程序本身仍保持轻量等待，方便再次打开 Docker Desktop 后恢复 worker。
- 关闭 Docker Desktop 主界面窗口并不一定退出后台程序。因此需要使用托盘菜单的 Quit/退出，才会联动停止。
- manager/download 的短暂服务重启不会直接停止已有 worker；worker 使用既有断连恢复机制。异常退出采用退避，连续多次失败后等待五分钟再检查，不忙循环。
- 注销或重启 Windows 后，管理程序也结束；下次该用户登录时计划任务自动启动。未登录时不运行。
- 原来的手动前台 worker 已在无活动下载任务时停止并转交管理任务。不要额外启动手动 worker。

## 文件与日志

Windows 本地管理程序、无密钥路径配置及状态在：

`%LOCALAPPDATA%\TelegramVideo2TextAdapter\launcher`

其中 `windows_supervisor.py` 为独立项目源码副本，`settings.json` 仅保存程序/配置路径；`status.json` 显示状态及所管理进程 PID；`supervisor.log` 每份最多 1 MiB、最多三份，只记录固定状态，worker 输出不写入该日志。它不依赖 Codex 聊天或 SSH 会话存活。

worker 源码仍通过 WSL UNC 加载，管理程序在需要时打开 Ubuntu；媒体/spool、凭据仍使用原独立 Windows JSON 配置，没有复制原 Windows 项目、历史浏览器状态或媒体。Docker 配置和证书依然使用既有角色运行卷。

## 暂停与恢复

在 Windows PowerShell 暂停本项目联动（不停止 Docker）：

```powershell
Disable-ScheduledTask -TaskName 'Video2TextLocal-DockerFollower'
Stop-ScheduledTask -TaskName 'Video2TextLocal-DockerFollower'
```

恢复：

```powershell
Enable-ScheduledTask -TaskName 'Video2TextLocal-DockerFollower'
Start-ScheduledTask -TaskName 'Video2TextLocal-DockerFollower'
```

查看状态：

```powershell
Get-ScheduledTask -TaskName 'Video2TextLocal-DockerFollower' | Select-Object TaskName,State
Get-Content "$env:LOCALAPPDATA\TelegramVideo2TextAdapter\launcher\status.json"
```

程序只保有自己启动的子进程句柄，通过专用 Job Object 关闭该进程树，不按 Python/Chromium 名称批量结束其他进程。

## 验证范围

- 五项单元测试通过：等待就绪、短暂接口故障不停止已有 worker、退出停止、重开启动、异常退避。
- 真实 Windows 受控进程测试通过：停止 worker 及其后代，重新创建；当前 Docker Desktop 进程检测通过。证据：`verification/supervisor/native-check.json`。
- 实际计划任务 Running，RunLevel Limited，Interactive 用户登录；唯一 worker 存在，mTLS 请求成功。证据：`verification/supervisor/live-status.json`。
- 真实 Docker Desktop Quit/重新打开及下一次 Windows 登录自动触发：尚未实测，不能以受控进程测试代替。用户空闲时退出 Desktop，等十秒再打开，并向机器人提交一条抖音链接/选择原稿即可进一步验收。

退出时正在进行的任务可能超过原租约而失败；原媒体/journal/数据库保留，恢复后按机器人“重试未完成阶段”处理。联动不修改租约，也不保证跨退出的在线下载永不中断。没有删除目录/卷，没有更改驱动、代理、DNS或旧项目。
