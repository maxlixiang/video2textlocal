# 新抖音链接原稿测试

2026-10-12，用户授权一次真实测试。配置位于新项目 `.env`，读取时未输出秘密；getMe 与指定测试机器人 ID 一致，白名单唯一收件人聊天可达，无 webhook，没有启动长轮询。

结果：通过。`https://v.douyin.com/3RnVIQ3F_aY/` 解析到作品 `7695668425309392166`，Windows 干净匿名上下文下载 16,131,524 字节、约 212.11 秒媒体。两侧哈希/完整音轨解码通过；Docker FunASR 1.2.7 / Torch 2.5.1+cu121 在 RTX 4060 Ti 上 cuda + float32 实际识别 113 段，UTF-8 时间戳原稿已由测试机器人 sendDocument 成功发送到唯一白名单聊天。成功任务链约 49.48 秒，包括下载、交接、识别和发送。

Windows 子树 private commit 采样峰值 1,363,324,928 字节，维持默认 2 GiB 内核预算，未在本轮调整额度。GPU PyTorch 峰值分配 2,463,302,144 字节；整卡峰值 4606 MiB 包含其他进程。

首轮因为协调器尚未就绪，工作进程退出，任务报 adapter_unavailable；尚未请求抖音。增加测试脚本有界就绪等待后恢复同一任务，在线下载成功一次。保留 startup-not-ready.json 作为证据，不将该启动问题归因于平台限制。

本次为用户授权直接提交任务，实际执行 Manager.process、持久化任务/发送记录、真实 Windows 下载、Docker GPU 以及 Telegram 状态与附件发送。**不代表通过 Telegram 收到链接、按钮点击和长轮询完整入口已实测。** 用户要求为原稿转写，本次未调用 DeepSeek；密钥填写不等于模型可用和整理验收通过。

证据：preflight.json、windows.json、result.json、startup-not-ready.json、原稿 Markdown。未输出 Cookie 值、签名媒体地址、密钥。测试后所有本次服务已停止，Windows 前台工作进程已结束，测试卷和文件保留。原项目、旧部署和全局网络没有修改。
