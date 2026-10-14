# 2026-10-14 当前修复与验证状态

本次提交汇总：完成任务媒体保留72小时、Docker持久配置/分角色凭据、专用CA轮换与续期、Windows下载worker与Docker Desktop联动、磁盘错误分类修复。当前日常镜像标签storage-fix；上传源码不重启服务、不自动重建镜像、不改变原数据卷。

| 验证 | 状态 |
|---|---|
| 最终隔离回归 | 66项通过（含新增目录访问失败分类、Desktop联动、readiness、媒体保留测试） |
| 固定媒体CA轮换 | 通过：4MiB上传断点、同generation、不重复下载、Windows/Docker音轨解码、旧CA撤销、新客户端继续访问、重复确认 |
| 在线角色凭据 | 已核查：manager仅内部密钥；download仅自身服务证书/私钥、公开CA、worker映射与内部密钥；GPU无适配器凭据，均无CA签发私钥 |
| Windows联动受控测试 | 通过：等待、启动、停止自身进程树、重新启动；实际低权限登录任务和唯一worker运行，mTLS连接成功 |
| 真正Desktop Quit/重开与下次登录触发 | 尚未实测 |
| 修复后的真实Windows重启 | 尚未实测 |
| 最新抖音磁盘提示失败任务 | 下载阶段失败；核查时两侧空间充足；代码曾将文件访问异常映射disk_full，已改分类与短暂重试。精确历史Windows异常尚未捕获，真实重试尚未验证 |
| 真实Telegram/DeepSeek三平台验收 | 此前已完成，见FIX-REPORT.md；本次66项隔离测试不替代真实端到端重验 |

当前源码和最新日常操作优先见 REBOOT-RECOVERY.md、CERTIFICATE-LIFECYCLE.md、WINDOWS-DOCKER-FOLLOWER.md、MEDIA-RETENTION.md、STORAGE-FIX.md。历史报告/旧启动命令保留用于追溯，不能用于认定最新部署状态。

详细原始脱敏证据留在宿主 verification/storage-fix、verification/recovery、verification/supervisor、verification/retention。整个verification目录不上传，避免混入凭据路径配置、私人转写、媒体、数据库与诊断材料；本表只公开验证结果及局限。

标准Dockerfile同步包含公开build_tools模块，使新联动单元测试可在新构建的测试镜像导入；当前storage-fix镜像已包含该模块。新构建所需wheelhouse仍按README固定依赖流程本机准备，不上传模型或包缓存。没有重跑在线测试或重启任何服务。
