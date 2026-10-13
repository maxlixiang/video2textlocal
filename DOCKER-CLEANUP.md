> 历史盘点记录：用户后来已手动执行清理已停止容器与构建缓存的命令，以下数量不代表当前状态。

# Docker 人工清理清单（只读盘点，未删除）

当前核查：51 个容器，3 个运行、48 个已退出；镜像实际合计约 14.19GB，构建缓存独占可回收约 7.22GB。图中镜像 11.85GB/9.21GB 等大小包含共享层，不能直接相加。

## 必须保留

- 容器：v2t-live-fixes-manager-1、v2t-live-fixes-download-1、v2t-live-fixes-gpu-1。
- 三个 telegram-video2text-*:fixes-final 镜像。
- telegram-video2text_models，以及 v2t-live-fixes_database/media/results 卷。其余卷本轮也不清理。
- 独立项目源码、verification 脱敏证据、Windows 凭据和 spool。

## 可逐个人工删除的已退出测试容器

删除会丢失容器自身的日志和可写层；已保存的报告和挂载卷保留。先确认不需容器内的额外日志。操作前刷新状态，若已运行则停止清理并核对。Docker Desktop 每次删除一个明确容器，不选删除关联卷，不用批量选择。

- `v2t-fixes-protocol-download-1` — Exited (143) 13 minutes ago
- `v2t-fixes-protocol-coordinator-1` — Exited (143) 13 minutes ago
- `v2t-fixes-regression-final-v4` — Exited (0) 21 minutes ago
- `v2t-fixes-regression-final-v3` — Exited (0) 32 minutes ago
- `v2t-fixes-custom-final` — Exited (0) 39 minutes ago
- `v2t-config-check-gpu-1` — Exited (143) 37 minutes ago
- `v2t-fixes-regression-final-v2` — Exited (0) 40 minutes ago
- `v2t-fixes-unit-final` — Exited (0) 50 minutes ago
- `v2t-fixes-browser-controlled-2` — Exited (0) 55 minutes ago
- `v2t-fixes-config-check` — Exited (0) 57 minutes ago
- `v2t-fixes-browser-controlled` — Exited (1) 59 minutes ago
- `v2t-fixes-unit-2` — Exited (0) About an hour ago
- `v2t-fixes-unit-1` — Exited (1) About an hour ago
- `v2t-terminology-unit-final` — Exited (0) 2 hours ago
- `v2t-terminology-polish-aliases` — Exited (0) 2 hours ago
- `v2t-terminology-polish` — Exited (0) 2 hours ago
- `v2t-terminology-unit` — Exited (0) 2 hours ago
- `v2t-terminology-gpu` — Exited (0) 2 hours ago
- `v2t-hotword-parser-probe` — Exited (0) 2 hours ago
- `v2t-interaction-unit-polish` — Exited (0) 3 hours ago
- `v2t-interaction-accept-coordinator-1` — Exited (0) 3 hours ago
- `v2t-interaction-unit-final` — Exited (0) 3 hours ago
- `v2t-interaction-silent` — Exited (0) 3 hours ago
- `v2t-interaction-accept-download-1` — Exited (143) 3 hours ago
- `v2t-interaction-accept-gpu-1` — Exited (143) 3 hours ago
- `v2t-interaction-unit` — Exited (0) 3 hours ago
- `v2t-douyin-accept-coordinator-1` — Exited (0) 3 hours ago
- `v2t-douyin-accept-gpu-1` — Exited (143) 3 hours ago
- `v2t-douyin-accept-download-1` — Exited (143) 3 hours ago
- `v2t-douyin-telegram-preflight` — Exited (0) 3 hours ago
- `v2t-adapter-test-download-1` — Exited (143) 4 hours ago
- `v2t-adapter-test-coordinator-1` — Exited (143) 4 hours ago
- `v2t-adapter-real-funasr` — Exited (0) 8 hours ago
- `v2t-adapter-test-database-permission` — Exited (0) 8 hours ago
- `v2t-adapter-fixed-media` — Exited (0) 8 hours ago
- `v2t-douyin-actual-domain-dns` — Exited (0) 10 hours ago
- `v2t-douyin-d-7692332665168465178-20261012t072519z` — Exited (1) 10 hours ago
- `v2t-douyin-d-7692261748124177640-20261012t072519z` — Exited (1) 10 hours ago
- `v2t-douyin-d-7695089785269996809-20261012t072519z` — Exited (1) 10 hours ago
- `v2t-douyin-network-check` — Exited (0) 10 hours ago
- `v2t-douyin-native-runtime-source-02` — Exited (0) 10 hours ago
- `v2t-douyin-native-runtime-source` — Exited (0) 10 hours ago
- `v2t-final-funasr-check` — Exited (0) 10 hours ago
- `v2t-final-whisper-check` — Exited (0) 10 hours ago
- `telegram-video2text-gpu-1` — Exited (143) 10 hours ago
- `telegram-video2text-download-1` — Exited (143) 10 hours ago
- `v2t-manager-recovery-check` — Exited (0) 11 hours ago
- `v2t-offline-media-resume` — Exited (0) 12 hours ago

## 容器引用解除后可逐个删除的旧标签

- telegram-video2text-manager:local
- telegram-video2text-download:local
- telegram-video2text-gpu:local
- telegram-video2text-manager:fixes
- telegram-video2text-download:fixes
- telegram-video2text-gpu:fixes

这些旧版本主要共享最终镜像的依赖层，预计只节省几 MB，不能按显示的整幅镜像大小计。删除被容器引用的镜像前，先处理对应已退出容器；不要强制删除正在使用的镜像。

pytorch/pytorch / 831247999fbf 是 GPU 共享基础层，独占约 6KB；删除不会释放显示的 9.21GB，建议保留以利后续构建。

## 真正值得关注的空间

- 已退出容器合计可写层约 85.95MB，清理主要让列表更清楚。
- 构建缓存独占可回收约 7.22GB，才是本次可能释放最多的项目；共享约 9.92GB 不能作为额外释放计算。清缓存不改变已建好的镜像和模型卷，但下次构建可能重新下载依赖。
- 本轮遵守既有限制，不执行 prune、批量删除或全量重置。缓存清理需要由用户人工选择明确范围；不能把 Docker Desktop 的全量数据清除当成清理缓存。
- Docker 内部释放空间不保证 Windows 的虚拟磁盘文件立即缩小。本轮没有执行虚拟磁盘压缩、停止 WSL 或其他宿主级操作。

盘点时三台服务健康运行。本文件仅为人工清单，不是自动清理脚本。
