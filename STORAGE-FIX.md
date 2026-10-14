# 2026-10-14 暂存空间提示诊断与修复

任务 `769be59b78bb4f29933f250835979e60` 在下载阶段失败，尚未进入 FunASR。Windows journal 为 disk_full，存在未完成媒体，download.json 未生成；采样浏览器进程树峰值约1.19GB，低于6GiB预算，不能归因为内存溢出。

只读核查时 Windows 暂存所在卷剩余90,737,287,168字节，Docker媒体/结果/数据库所在卷剩余996,436,668,416字节；Windows暂存约64MB、额度4GiB，Docker媒体约102MB。Windows下载前预留792,723,456字节并要求剩余至少2GiB。以上实测没有显示容量不足，不建议为这条提示删除文件或降低保护阈值。

代码 `v2t/adapter_common.py` 原本把暂存遍历、文件stat与磁盘信息查询的部分OSError也映射为disk_full。该任务浏览器运行期间可能遇到目录访问/临时文件并发变化；历史证据没有保存具体异常类或winerror，不能证明某一种Windows文件锁或其他精确原因，也不能完全排除当时瞬时余量与核查时不同。

本轮修改：对完整暂存扫描进行最多三次短暂重试；仍无法读取时返回storage_unavailable，记录固定异常类型、errno/winerror、操作阶段和时间到spool `.storage-check.json`，不记录路径、URL、文件名或内容。只有实测free减预留低于阈值仍返回disk_full，总额度保护不变，不跳过不可读文件绕过额度。新用户提示明确区分目录读取失败与真实容量不足。

66项隔离回归通过，含短暂访问异常恢复、持续读取失败分类、查询磁盘失败分类和真实低余量保护，见 `verification/storage-fix/unit.log`。三服务已切换到storage-fix镜像，健康；当前用户Docker联动任务已重载，唯一Windowsworker与mTLS连接正常。没有删除文件或改变空间额度、网络、驱动、TLS。

该任务真实重试仍待用户在Telegram点击“重试未完成阶段”。这次实际下载尚未成功，不将代码修复或模拟测试写成真实抖音验收通过。
