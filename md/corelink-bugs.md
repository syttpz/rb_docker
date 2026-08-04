# Corelink C++ client bug review

范围：`src/bridge_node/corelink_cpp` 以及 `CorelinkTransport` 对它的调用。



## CL-04：UDP receiver 可能同时启动两个 receive 操作

- 严重度：P0
- 证据：代码确认
- 位置：`corelink_cpp/src/core/corelink_data_xchg_udp_proto_manager.cc:188-208`

成功收到 datagram 后，如果 `socket->available()` 非零，代码在分支内调用一次 `start_receiver()`；退出分支后，只要 `reentrant` 为 true，又调用一次。

这会让同一个 socket 上出现两个 outstanding receives，而且两者使用同一个 `channel_impl->receive_buffer`。回调先后顺序不确定，数据可能被另一个 receive 覆盖。

## CL-05：UDP 被错误地按字节流累计

- 严重度：P0/P1
- 证据：代码确认；实际影响需抓包验证
- 位置：`corelink_cpp/src/core/corelink_data_xchg_udp_proto_manager.cc:190-205`

UDP 保留 datagram 边界，一次 receive 就应该对应一个 datagram。当前实现却：

- 用 `bytes_read += bytes_transferred` 累计长度；
- 下一次 receive 仍写入同一个 buffer 的起点，而非 `buffer + bytes_read`；
- 根据 `socket->available()` 决定是否把累计内容交给上层。

当队列中还有 datagram 时，旧数据可能被新 datagram 从头覆盖，而 `bytes_read` 仍是两者长度之和，随后复制出“新数据 + buffer 中残留数据”。这可能导致所谓 coalesced buffer、重复分片或损坏 payload。

建议复现：连续发送带固定填充值和长度的 datagram（例如 A=1000 字节、B=2000 字节），在接收回调记录每个 buffer 的长度、hash 和头部。

## CL-06：全局 packet escrow 会循环覆盖在途发送 buffer

- 严重度：P1
- 证据：代码确认设计缺陷；触发阈值需压力测试
- 位置：
  - `corelink_cpp/include/core/corelink_network_global_packet_hold.hpp:14-45`
  - `corelink_cpp/src/core/corelink_network_global_packet_hold.cc:5-27`

异步发送的数据存入 1024 个全局 vector slot，slot index 循环使用。系统没有记录 slot 是否仍被 `async_write/async_send_to` 引用。第 1025 次尚未完成的发送可以覆盖第 1 次发送的 vector。

锁只保护容器读写操作，不能保护 buffer 在整个异步 I/O 生命周期内保持不变。`get_packet()` 返回引用后立刻释放读锁，也无法阻止后续 override/clear。

原始 RGB 帧约 49 个分片；只需约 21 帧的发送积压就可能跨过 1024 slot。

## CL-07：`concurrent_counter` 的回绕操作不是原子的整体操作

- 严重度：P2
- 证据：高风险潜在问题
- 位置：`corelink_cpp/include/utils/concurrent_counter.hpp:106-121`

代码先原子读取/比较，再 `fetch_add` 或 `store`；“检查是否达到上界并决定回绕”不是一个原子事务。多个 I/O 线程并发分配 slot 时，可能得到越界值、重复 slot 或不符合预期的回绕顺序。



## CL-09：异步回调和 detached thread 存在对象生命周期竞态

- 严重度：P1/P2
- 证据：高风险潜在问题
- 位置：
  - `corelink_data_xchg_raw_socket_protocol_context_manager.cc:18-59`
  - `corelink_client.hpp:218-220`
  - `corelink_transport.cpp` 中捕获 `this` 的回调

I/O context threads 被 `detach()`；多个 callback 捕获 client 或 bridge 的裸 `this`。关闭节点时，析构和 pending callback 之间缺少显式 join/cancellation barrier。

需要用重复启动/关闭、ASan/TSan 或 callback 中人工延迟验证是否存在 use-after-free。修复前不能仅凭静态代码断定必然触发，但生命周期模型不安全。

## CL-10：错误回调使用了错误的 channel id

- 严重度：P2
- 证据：代码确认
- 位置：`corelink_cpp/include/core/corelink_client.hpp:850-861`

MTU 超限时调用 `channel_descriptor->on_error(1, ...)`，固定传入 1，而不是实际 `data_channel_channel_id`。多 channel 调试时日志会错误归因。

## CL-11：receiver 初始化时发送空 data frame，语义和错误处理不清晰

- 严重度：P2
- 证据：潜在问题
- 位置：`corelink_cpp/include/core/corelink_client.hpp:337-343`

receiver 的 `on_init` 会调用 `send_data(ch_id, empty packet, empty headers)` 作为 ping。它仍会构造完整 Corelink data header；如果服务器协议并不要求/接受 receiver data-channel ping，可能制造伪 frame 或错误。需要对照服务器协议和抓包确认。

## 与现有 benchmark 的关系

`REALSENSE_UDP_BENCHMARK.md` 中 TCP 60 秒仅收到 3/900 帧，不应只归因于一个点。CL-01、CL-02、CL-03 和 CL-08 都可能参与；应先构造可控 TCP 流逐项验证，再重新跑相机 benchmark。
