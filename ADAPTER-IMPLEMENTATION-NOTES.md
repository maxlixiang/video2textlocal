# 适配器实施边界

适配器默认关闭。本轮只改独立新项目，不注册 Windows 服务/计划任务，不改原项目、旧部署或全局网络。

1. manager 的控制HTTP线程用 run_coroutine_threadsafe 将短数据库操作交给唯一事件循环；下载等待为异步轮询，不在事件循环做网络、hash、FFmpeg或块写入。网关控制请求独立于媒体上传/解码线程，无 manager↔download 同步等待环。
2. Windows父进程独立心跳线程；浏览器在受Job Object预算限制的子进程，上传在主工作线程。完整上传验hash并被manager接纳后转为服务端 owned validating：不再因Windows心跳消失失效，Docker可恢复验收；有独立180秒验收期限，成功收据可在重启后补交。
3. 排队期限默认300秒，从用户最新入队时间计；领取才开始600秒执行期限，心跳不延长硬期限。上传接纳前须未过执行期限；接纳后使用独立验收期限。每次用户重试可重新入队，旧generation不能提交。
4. Windows spool默认4GiB、最低剩余2GiB，预留500MiB媒体+256MiB浏览器临时空间；Linux media默认8GiB、最低剩余2GiB，预留媒体+最长PCM音轨。保留的失败文件/完成媒体也计入总量；配额不足明确失败，不自动清理。
5. mTLS每次新连接读取当前证书；仅专用CA和worker指纹映射可认证。到期握手拒绝；临期不领取新任务。更新时允许新旧证书指纹映射同一worker，原子替换专用文件，不修改系统信任。已接纳媒体的验收不依赖客户端证书；更新后查询同一任务，未完成媒体可在新generation下复用。
6. 实测Windows Job Object整体private-commit峰值及Python/Node/Chromium进程数，预算默认2GiB；本地超预算故障注入和真实APIRequestContext缓冲下载分别记录。声明长度/文件限额不能代表内存预算。心跳不在受预算的浏览器子进程中。
