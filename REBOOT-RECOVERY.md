# Windows 重启后的恢复记录与操作

2026-10-13，用户报告台式机重启并重新打开 Docker Desktop 后 Telegram 无响应。

只读检查发现：GPU/download 容器显示 healthy，manager 反复重启；GPU `/configuration` 返回 invalid_input。宿主 config/hotwords.txt 存在，而容器内只读配置目录没有该文件；下载容器内专用 CA/server 证书也不可见。重建本项目容器后这两个挂载都恢复，GPU 配置接口正常，manager 开始处理先前的链接，任务到 choice，发送输出选择按钮。Windows 专用 mTLS 握手通过，重启后没有实际 Windows worker，手动前台启动后 manager 记录到连接。

已确认的是重启后的挂载缺失；Docker Desktop 内部挂载/启动顺序原因尚未进一步隔离。不能把“容器运行/healthcheck通过”或“Docker Desktop已打开”当作完整恢复已验证。现有 healthcheck 只检查 HTTP 存活，未覆盖配置/证书存在性。

没有重建镜像、修改识别代码、删除卷、修改全局网络/驱动或注册启动项。恢复使用原 fixes-final 镜像和原数据卷。

## 遇到相同情况

先启动 Docker Desktop，确认 Ubuntu/WSL 能访问项目。在 Ubuntu 终端执行：

```bash
cd /home/codex/workspace/telegram-video2text
sg docker -c 'BOT_ENV_FILE=.env ADAPTER_CREDENTIALS_DIR=/home/codex/workspace/telegram-video2text/.adapter-pki WINDOWS_ADAPTER_ENABLED=1 ALLOW_FAKE_IP_DNS=1 docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot up -d --no-build --force-recreate'
```

这是本项目容器的重建，会短暂中断正在运行的任务；保留所有数据卷，不删除缓存/媒体/数据库，不需要重新构建镜像。仅在重启恢复异常时使用，不用于每次提交视频。

Windows worker 按 FIX-OPERATIONS.md 的明确 PowerShell 命令手动启动。先确认没有已有 worker，避免第二进程；当前已恢复的前台进程保持运行。配置和凭据不得粘贴到聊天。

检查 Telegram 是否出现输出选择按钮；收到按钮后再选择原稿/两稿。本次验证到更新处理、按钮任务、专用 TLS 和 worker 连接；未新增实际 ASR 推理测试，nvidia-smi 成功不等于本次重新完成 GPU 推理验收。
