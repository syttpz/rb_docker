# Bug review index

这组文档记录 2026-08-03 对 `rb_docker` 仓库的静态审查结果。目的不是说明修复方案已经实现，而是给后续逐项理解、复现、修复和提交 bug report 提供基线。

## 证据等级

- **已复现**：已经用最小测试触发，或已有仓库 benchmark 直接观察到现象。
- **代码确认**：仅从控制流、边界条件或 API 使用方式即可确认缺陷存在，但尚未做完整端到端复现。
- **高风险潜在问题**：代码高度可疑，需要定向测试才能确认实际运行影响。
- **维护/实验风险**：不一定是运行时 bug，但会导致部署与预期不一致，或使论文数据无法可靠解释。

## 文档

1. [Corelink 客户端问题](corelink-bugs.md)：TCP/UDP framing、异步 I/O、发送缓冲区和生命周期。
2. [Bridge 与分片问题](bridge-fragmentation-bugs.md)：分片正确性、多 sender、参数和 ROS 回调线程。
3. [部署、脚本与文档问题](repo-pipeline-bugs.md)：Docker、rosbag、Zstd、凭据及失效文档。
4. [实验有效性风险](experiment-validity.md)：当前 benchmark 为什么还不能直接支撑论文结论。

## 建议处理顺序

| 优先级 | 问题 | 理由 |
|---|---|---|
| P0 | TCP 短头丢弃和解析越界 | 会破坏字节流 framing，且包含未定义行为 |
| P0 | UDP 重复 `async_receive` / 共享接收缓冲区 | 可能直接损坏或重复收到的数据 |
| P0 | Reassembler 接受缺失 sequence 的帧 | 会把损坏的 CDR 当作完整 ROS 消息发布 |
| P1 | TCP 并发写与全局 1024-slot escrow | 高频流量下可能覆盖或破坏在途数据 |
| P1 | 多 sender 共用 frame number 空间 | 可把不同机器/进程的分片拼成一帧 |
| P1 | 建立可配对的端到端实验记录 | 否则丢包率和延迟无法精确归因 |
| P2 | 生命周期、参数验证、错误状态 | 影响恢复能力和边缘条件稳定性 |
| P2 | Docker、脚本和 Markdown 漂移 | 当前部署不一定运行当前源码或记录预期 topic |

## 审查时做过的验证

- `bash -n`：仓库 shell 脚本语法通过。
- `python3 -m py_compile`：Python/launch 文件语法通过。
- 分片最小测试：921,672 字节数据拆成 49 片，逆序输入可以重组。
- 分片反例：缺少 sequence 0、但额外存在 sequence 2 时，Reassembler 错误输出“完整帧”；已复现。
- Corelink 本机构建：配置成功，但宿主机缺少 `asio.hpp`，因此没有完成库构建。这是本机依赖限制，不作为仓库 bug 证据。

除新增本目录文档外，本轮没有修改实现代码。
