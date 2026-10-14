# 视频和音频保留机制

已启用：成功完成任务后保留 **72 小时**，程序运行时每小时检查一次（启动后也检查）。清理按任务和具体文件逐一执行，不删除整个目录，不调用 prune，不处理旧项目或其他 Docker 卷。

## 文件位置

- Docker：命名卷 `v2t-live-fixes_media`，容器路径 `/media/<任务ID>/media.bin`、`audio.wav`。YouTube/X 直接保存到这里；抖音交接后也保存一份。
- Windows 抖音下载：`C:\Users\justd\AppData\Local\TelegramVideo2TextAdapter\fixes-20261013-002320\real-spool\<任务ID>\media.complete`，临时媒体为 `media.part`。
- 原稿和整理稿：Docker `v2t-live-fixes_results` 卷，`/results/<任务ID>/`。目前长期保留，受结果额度保护，三天清理不删它们。
- 模型、数据库、证书、配置、元数据、已发送的 Telegram 消息都不受媒体清理影响。

## 保护条件

只清理数据库中已成功完成、完成时间超过 72 小时的任务，且具体媒体文件也超过 72 小时。排队、处理、上传、验收、失败待重试均排除；较新的文件延后处理。允许删除的文件名限定为媒体、音频及本任务媒体临时文件。拒绝越界任务 ID、符号链接和 Windows junction/reparse 路径。文字文件和模型文件即使放在测试任务目录，也不能被清理。

manager 是唯一 SQLite 状态写入者，Docker 下载服务在内部认证接口收到授权后，每次只删除一个明确文件。Windows worker 空闲时通过专用 mTLS 获取自己的到期任务，并在每次删除前再次向 manager 校验资格，保留开关关闭或状态变化后不能继续用旧授权删除。Windows 文件仍在自己的独立 spool 内操作。

失败任务不自动删除，因为它们还需要重试；其媒体会继续占用磁盘，原有总额度和最低余量保护仍有效。诊断文件、浏览器残留缓存、小型元数据、数据库也不会由该机制全部清空。

程序关闭时不清理。Docker 再次启动后检查 Docker 媒体；Windows worker 再次前台运行且能连接 manager 后检查 Windows 媒体。Windows worker 不运行时，其本地副本仍保留，不注册任务计划或服务。

## 配置

```ini
MEDIA_RETENTION_DAYS=3
MEDIA_CLEANUP_INTERVAL_SECONDS=3600
```

配置在 Compose 的共享参数中统一传给 manager/download。天数设为 `0` 可关闭；更新参数后重新部署对应 Compose 并重启 Windows worker。当前需要 `compose.adapter.yaml` 提供专用内部认证凭据；缺少该凭据时不执行 Docker 删除并记录固定提示，而不是无认证清理。

到期后若想再次下载同一视频，需要新建任务并重新在线下载；不要把已清理媒体的任务当作永久下载缓存。已完成的文字稿保留；失败整理任务因状态未完成而保留媒体，仍可按原有阶段重试。

## 本轮验证与版本

- 52 项隔离回归通过（新增 7 项保留机制用例）。
- 实际 Docker 夹具：四天前已完成任务的媒体/音频被清理，处理中任务保留；文字/元数据/模型均保留。
- 实际 Windows 夹具：专用 mTLS 授权后清理四天前完成媒体和临时媒体，文字/元数据和目录保留。
- 本轮未访问视频平台、未调用 ASR/DeepSeek 重做在线测试。
- 当前真实任务没有完成超过 72 小时的记录；部署前后真实媒体数量、字节数和内容汇总 hash 完全一致，没有提前删除。
- 证据在本机 `verification/retention/unit.log`、`docker.json`、`windows.json`、`live-media-before.json`、`live-media-after.json`。
- 当前三服务镜像标签为 `retention`，保留原 `fixes-final` 镜像供回退，依赖层直接复用已验证镜像，未重新安装包或模型。源摘要及实际部署清单在 `verification/retention/`；旧 FIX-REPORT 的镜像和平台验收是此前版本历史证据。

用户本轮明确授权三天自动媒体清理，它是此前禁止自动批量清理的限定例外。其他文件、目录、容器和卷仍不自动批量删除。
