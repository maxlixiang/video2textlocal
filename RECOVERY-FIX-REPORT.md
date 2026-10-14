# 重启、CA 生命周期与凭据隔离集中修复

日期：2026-10-13。基线提交 df2d41e31ed73ee7ff05a26eb823e329cfc64f1a；本轮与此前媒体保留功能尚为工作区修改。运行版本以 `verification/recovery/source-manifest.json` 内容摘要及 `runtime-audit.json` 镜像 ID 为准，不能称为已推送提交。三个运行镜像使用 `:recovery`，没有源码开发 bind 挂载。

## 修改与依据

| 项目 | 修改 | 验证与限制 |
|---|---|---|
| 重启缺配置/证书 | 日常 Compose 用 Docker 配置卷与分角色运行卷，撤除 WSL config/整个 PKI bind；启动工具检查源文件再初始化卷 | `compose.final.yaml`、`compose.adapter.yaml`、`build_tools/prepare_runtime.py`；实际在线挂载审计见 runtime-audit.json。Desktop 原空 bind 具体触发机制仍未隔离 |
| 启动顺序 | manager 开始长轮询前等待 download/GPU readiness、核对实际识别配置；Engine 重启不依赖 Compose 再次排序 | `v2t/manager.py`；独立 manager 单实例原数据库锁保留。无法就绪时不开始轮询 |
| 健康检查 | HTTP 503 反映配置/模型锁/GPU可见性/磁盘与启用时 mTLS 缺项，manager 标记定期更新且过期无效 | `v2t/readiness.py`、`v2t/service.py`；实际缺配置 503 见 missing-config-readiness.json。不是实际 GPU 推理或平台连通性保证 |
| CA 生命周期 | 专用一年 CA、90 天叶证书，签发与导出分开，双信任过渡后撤销旧 CA | `build_tools/runtime_credentials.py`；真实固定媒体上传恢复见 ca-rotation.json。旧 CA 已从日常在线信任中撤销 |
| 更新提醒 | CA 提前30天、叶提前14天；状态工具、health 警告、manager 每天至多一次白名单既有聊天通知 | `runtime_certificate_status.py`、manager monitor、worker；提醒逻辑代码已部署，真实未来到期 Telegram 通知未触发验证。电脑关闭不发通知 |
| 凭据范围 | manager 仅内部密钥；download 仅自身叶证书/私钥、公开CA/映射和内部密钥；GPU没有适配器凭据 | runtime-audit.json：三者 CA 签发私钥可读均为 false。签发目录未进入镜像、卷或 Windows |

## 实测

| 测试 | 结果 | 证据 |
|---|---|---|
| 回归测试（含缺配置、参数不匹配、缺凭据、过期健康标记） | 57项通过 | verification/recovery/unit.log |
| 实际 GPU 服务缺热词文件 | HTTP503，ready=false | missing-config-readiness.json |
| 上传中断后 CA 改变 | 新服务器CA仍接受旧客户端（短暂双信任），保留4MiB已确认偏移 | ca-rotation.json |
| 新CA客户端恢复同任务 | generation不变、媒体未重下载、双侧全音轨解码和hash一致 | ca-rotation.json |
| 撤销旧CA | 旧客户端失败，新客户端继续访问完成任务 | ca-rotation.json；旧客户端收到握手关闭归类 adapter_network，而非精确证书错误。新客户端同时间成功，不能据此称为出口网络问题 |
| 轮换后重复确认 | 返回duplicate，不再提交任务 | ca-rotation.json |
| 日常角色挂载 | 三服务healthy，无CA私钥，原四个数据/模型卷名称保留 | runtime-audit.json |
| Windows唯一 worker 与回环请求 | 实際进程1，mTLS请求成功 | windows-live.json |
| 真实 Windows 重启 | 等待用户执行，不算通过 | before-reboot.json 已保存12个原任务，quick_check=ok；待 after-reboot 证据 |

固定媒体测试为隔离协议验收，没有 Telegram、在线抖音、ASR 或 DeepSeek。不能替代本轮重启后的完整真实原稿流程，也不重新宣称三平台端到端全部重验。既有真实测试仍见 FIX-REPORT.md。

## 运行与操作

保留日常 `v2t-live-fixes` 三个服务和一个手动 Windows worker。隔离 `v2t-ca-rotation` 两个容器、缺配置负例容器已逐个停止，保留测试卷和证据，没有删除卷/目录或全局网络修改。旧测试证书文件留存但不再在线信任。当前代码/凭据无需 SSH 会话维持 Linux 容器，Windows前台 worker 仍随窗口关闭或登出停止。

启动、停止、重启步骤见 REBOOT-RECOVERY.md；专用 CA/叶证书续期、过渡和撤销见 CERTIFICATE-LIFECYCLE.md。现阶段适合单人继续受控使用；只有完成真实 Windows 重启、自动启动 Linux服务、手动恢复 Windowsworker、Telegram原稿送达后，才补记本轮重启验收通过。未承诺无人值守 Windows 自启动。
