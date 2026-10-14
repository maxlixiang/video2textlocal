# Video2TextLocal

Telegram 视频下载与本地 GPU 转文字机器人。YouTube/X 由 Docker 下载；抖音由独立 Windows worker 匿名下载并通过专用 mTLS 交接。任务管理、GPU 推理和 DeepSeek 整理保持在 Docker。使用 Telegram 云端 Bot API 与长轮询，不自动安装驱动或修改全局网络。

## 使用

发送受支持的视频链接，在两分钟内选择视频下载、原稿或原稿＋DeepSeek 整理稿；可在选择期限内切换本地识别引擎。抖音默认 FunASR，其他平台默认 Faster-Whisper。GPU 并发默认1，不静默回退CPU或云端。

/status 查询自己的等待、排队、下载、识别、整理和发送状态。/check 查询服务运行前提及Windows近期连接；不会下载媒体、运行推理或调用DeepSeek。两稿模式先发送原稿，再提示正在整理。失败可重试未完成阶段。

## 配置与构建

复制.env.example为本机配置，填写独立测试机器人Token、预期机器人ID、白名单用户ID与可选DeepSeek密钥；不得提交凭据。保持BOT_PURPOSE=test，启动时核对机器人身份，避免同一Token启动两个轮询进程。

Dockerfile、Dockerfile.gpu和requirements锁文件定义构建。GPU离线包由build_tools/fetch_wheels.py按固定版本及官方包哈希准备；wheelhouse、模型和运行数据不进入Git。通过Compose工具配置准备模型并完成实际GPU推理验证。

Compose按角色使用持久配置及凭据卷。build_tools/runtime_credentials.py离线签发、导出允许列表；prepare_runtime.py检查配置与凭据后初始化运行卷；start_local.sh启动同一Compose项目。首次安装须准备独立内部认证密钥、证书与worker配置，不能直接套用其他主机凭据。不同主机的项目名、模型卷和配置路径需按实际安装调整。

Windows工具使用本机Python：install_windows_supervisor.py安装当前用户Docker联动任务；restart_windows_follower.py等待旧进程实际退出后重载。不会修改Docker自启动；应按实际Windows用户名、WSL发行版和安装目录配置。

## 数据与维护

任务、媒体、结果和模型分卷持久化。完成任务的媒体默认保留三天，逐个文件清理；未完成任务、稿件、数据库和模型保留。不批量删除目录/卷。磁盘余量和总额度保护保留，日志轮转。

专用CA/叶证书使用有限有效期与到期提醒，支持双信任CA轮换。在线服务不挂载CA签发私钥。网络规则见NETWORK-POLICY.md；健康查询见HEALTH-CHECK.md；交互规则见INTERACTION-UPDATE.md。

## 验证边界

89项隔离回归通过；用户确认两分钟超时、任务状态和整理等待提示体验通过。健康命令真实用户入口仍待确认。公开报告不包含主机运行快照、测试任务标识或私人结果；模拟测试不等于平台下载、GPU推理、重启和网络全部验收通过。
