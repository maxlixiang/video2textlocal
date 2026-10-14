# 专用证书的维护与 CA 轮换

本方案只用于 Windows worker → Docker 下载服务的回环 mTLS，不加入系统信任根，不关闭证书验证。当前专用 CA 有效期一年，叶证书 90 天；证书生成默认使用这两个有限周期。CA 私钥保存在 Linux 项目 `adapter-offline/` 的离线签发目录（这里的“离线”指不挂载任何在线服务；并不意味着电脑离线）。目录以 umask 077 创建，禁止上传到 GitHub、复制到镜像或 Windows worker。原测试 `.adapter-pki` 私钥保留用于审计，已撤出所有在线容器挂载；不要继续使用旧签发工具作为日常入口。

当前 CA：2027-10-13 13:35:57 北京时间到期；叶证书：2027-01-11 13:35:57/58 到期。旧 CA 已撤销在线信任。以工具实际输出为准。

## 维护提醒

在项目目录执行 `python3 build_tools/runtime_certificate_status.py`，只输出公开有效期和维护日期。叶证书提前 14 天、CA 提前 30 天进入维护期。运行中的 download `/health` 返回固定警告代码；manager 每天最多向已使用本程序的白名单聊天发送一次维护提醒（通知结果记录在数据库卷内独立文件）；Windows worker 在叶证书维护期输出提示。没有运行的程序不会发提醒：请至少每月检查一次状态，不依赖临近到期抢修。临近到期 24 小时时启动工具拒绝部署；服务距离到期不足 15 分钟拒绝接入任务。

停止超过到期日期时，先执行下述签发和安装步骤，再启动。不能靠调整系统时间或关闭 TLS 验证恢复。

## 叶证书续期

以下命令在 Linux 项目目录运行。`<当前签发目录>`、`<新生成目录>` 以工具输出为准，不包含私钥值。

```bash
python3 build_tools/runtime_credentials.py issue --offline-directory adapter-offline --worker-id test-worker --authority '<当前签发目录>'
python3 build_tools/runtime_credentials.py export --generation '<新生成目录>' --runtime-directory .adapter-runtime --internal-key-file .adapter-pki/internal.key --overlap-old-directory .adapter-runtime/download/current
```

在 Windows 使用 Python 执行 `build_tools/windows_credentials.py --source '<新导出目录的实际 UNC 路径>' --config '<Windows worker 配置路径>' --trust-only`。这一步只更新公开信任链，保留旧客户端证书。Windows 无法可靠访问 Linux `current` 符号链接，因此必须使用 `.adapter-runtime/windows/generation-...` 实际目录。

然后在 WSL 执行 `sg docker -c 'python3 build_tools/prepare_runtime.py'`，最后在 Windows 再执行同一安装工具，去掉 `--trust-only`，切换新客户端证书。运行 worker 每个请求重新读取原子 manifest，无需关闭 TLS 验证。通过后按下述方式撤销旧指纹。CA 剩余有效期不足叶证书有效期加一天时，续期工具明确拒绝，必须轮换 CA。

## CA 轮换：先双信任，再换证，再撤销

1. 避开新的下载提交；确认现有工作仍在截止时间内。不要改变 worker 身份 `test-worker`、租约、generation、spool 或数据库。
2. 执行 `issue`，**不传 `--authority`**，生成新 CA 和新叶证书。保存原导出目录为旧公开信任来源，不复制 CA 私钥到任何运行导出。
3. 执行 `export`，`--overlap-old-directory` 指向旧 download 的实际 generation 目录（包含公开 ca.pem 与 workers.json）。新导出含新旧公开 CA、旧新客户端指纹，服务端叶证书来自新 CA。
4. **先**在 Windows 用新导出目录执行安装工具 `--trust-only`。现有客户端仍持旧叶证书，但已信任新旧服务器。
5. WSL 执行 `prepare_runtime.py`：将允许列表中的角色文件同步到 Docker 管理卷，原子切换 `current`。gateway 每次连接解析同一代的 server.pem/server.key；manager 仍使用原内部认证密钥。
6. Windows 再执行安装工具，不传 `--trust-only`，原子切换新客户端凭据。检查新客户端连接及待完成任务的 generation/上传偏移。服务端按稳定 worker 身份识别任务，不以证书指纹创建新任务。网络中断仍遵守既有租约、执行与验收截止时间；轮换不会延长过期任务。
7. 确认只有新 worker 凭据仍在使用后，重新 `export` **不传 overlap**，再 `prepare_runtime.py`。这会撤销旧 CA 与旧客户端指纹。必须验证旧客户端失败、新客户端成功；不能只凭文件替换宣称通过。

各步骤失败时停止后续操作，保留双信任直到恢复；不要提前撤销旧 CA。恢复使用已保存的实际 generation 和客户端 manifest，保持稳定 worker ID，不能清空 spool/数据库。临时双信任窗口应限定在一次维护中；不长期保留已经过期或不再使用的 CA。

## 权限与材料留存

manager 仅得到 internal.key；download 得到 internal.key、自身服务端叶证书/私钥、公开 CA、客户端指纹映射及公开有效期信息；GPU 无适配器凭据。Windows 仅得到客户端叶证书/私钥与公开 CA。所有在线挂载只读，**隔离的依据是允许列表与不同卷，不是只读标记**。

卷初始化器短时以容器 root 写文件并设 owner 1000，禁用网络，不挂载宿主签发目录，标准输入只传允许列表内文件；不会把 CA 私钥传入容器。旧 generation 会保留，用于手动审计/回滚；撤销信任不等于删除旧文件。旧证书材料由用户逐个明确路径维护，不自动批量清理。

实际 CA 轮换固定媒体验收：见 `verification/recovery/ca-rotation.json`。原上传确认 4 MiB，轮换后保持同 generation/偏移，未重新下载，Windows/Docker 全音轨解码通过，撤销旧 CA 后旧客户端被拒绝，新客户端继续完成和重复确认。测试使用独立端口 18768，不运行 Telegram/ASR/DeepSeek。
