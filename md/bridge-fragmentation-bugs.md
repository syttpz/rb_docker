# Bridge and fragmentation bug review

范围：`bridge_node.cpp`、`fragment.cpp/.hpp` 和 `CorelinkTransport`。

## BF-01：缺失 sequence 的帧可能被错误判定为完整

- 严重度：P0
- 证据：已复现
- 位置：`src/bridge_node/src/fragment.cpp:53-79`

完整性条件只有：

```text
seen_last == true && chunks.size() == last_seq + 1
```

它没有确认 map 中实际存在每个 key `0..last_seq`。

已复现反例：frame 99 收到 `(seq=1,last=true)` 和 `(seq=2,last=false)`，没有 seq 0；map size 为 2，`last_seq + 1` 也是 2，于是重组器输出 seq 1 + seq 2。

随后这段损坏数据会被作为 `rclcpp::SerializedMessage` 发布，问题可能表现为 ROS 反序列化错误，也可能成为字段值静默损坏。

## BF-02：最后分片标记可以被后来的异常分片改写

- 严重度：P1
- 证据：代码确认
- 位置：`src/bridge_node/src/fragment.cpp:49-52`

任意带 `is_last_fragment=true` 的分片都会覆盖 `last_seq`。代码不拒绝：

- 两个不同 sequence 都声称是 last；
- 已知 last 之后又到达更大 sequence；
- last_seq 变小或变大。

损坏/恶意 datagram 因此可以提前截断帧，或让帧永远等待不存在的分片。

## BF-03：协议头使用主机字节序

- 严重度：P1
- 证据：代码确认
- 位置：`src/bridge_node/src/fragment.cpp:21-23, 37-39`

`image_number` 和 `sequence_number` 通过 `memcpy` 直接写入 wire format，没有定义 network/little endian。当前 ARM64 Pi 和常见 amd64 都是 little-endian，因此暂时不暴露；协议本身仍不具备跨架构稳定性，也不利于独立抓包解析。

## BF-04：分片协议缺少 magic、版本、总长度和完整性校验

- 严重度：P1
- 证据：维护/协议风险

当前 9 字节头只有 frame number、sequence 和 last flag。receiver 无法验证：

- 收到的数据是否真是该分片协议；
- sender/receiver 是否使用相同协议版本；
- 最终字节数是否等于原帧；
- payload 是否在网络或内部 buffer bug 中被修改。

CRC 并非替代 UDP checksum，而是用于判断应用层重组结果是否完整可信。论文实验尤其需要区分“丢帧”和“损坏后被接受”。

## BF-05：不同 sender 的 frame number 空间会冲突

- 严重度：P1
- 证据：高风险潜在问题
- 位置：
  - `fragment.hpp` 中 `Slicer::cur_image_num{0}`
  - `corelink_transport.cpp` 的 `on_receive` 丢弃 `stream_id`
  - `Reassembler` 仅以 `image_number` 为 key

每个 sender 进程都从 frame 0 开始。Corelink receiver 可以订阅同一 stream type 下的新 sender，但 transport 没把 Corelink `stream_id` 传给 bridge，Reassembler 也不知道 sender identity。

两个 sender 同时发送相同 topic 时，其同号 frame 分片可能进入同一个 `PartialFrame`，相互覆盖或拼接。重连后如果 server 分配新 stream，同样存在碰撞可能。

## BF-06：frame number 回绕会破坏 stale eviction

- 严重度：P2
- 证据：代码确认边界问题
- 位置：`src/bridge_node/src/fragment.cpp:82-97`

`uint32_t` frame number 最终会从 `UINT32_MAX` 回到 0。`m_newest_image_number` 不会相应回绕，新的低编号 frame 会被视作非常旧；旧 frame 的差值计算也不具备 modular sequence number 语义。

15 Hz 下约 9 年才自然回绕，普通实验不紧急，但协议设计时应处理。

## BF-07：stale 清理只按新 frame 编号推进，没有时间和内存上限

- 严重度：P1/P2
- 证据：代码确认

如果流停止在一个缺片 frame，且之后没有足够多的新 frame 到来，该 partial frame 永远保留。更严重的是异常超大 sequence number 会向 `chunks` 插入数据，却没有：

- 每帧最大分片数；
- 最大重组字节数；
- wall-clock timeout；
- 全局 partial-frame 内存上限。

## BF-08：固定 19,000 字节 payload 没有使用 server 返回的实际 MTU

- 严重度：P1
- 证据：代码确认
- 位置：`fragment.hpp:28-34` 和 Corelink descriptor 的 `max_tx_unit`

Corelink wire frame 还包含 8 字节 Corelink header 和 JSON header。19,000 在当前 20,000 MTU 下有余量，但如果 workspace/server/path 协商出更小 MTU，所有分片仍会被拒绝。反之 MTU 更大时又产生不必要的分片开销。

`max_tx_unit` 已存在 Corelink data-channel descriptor 中，但没有通过 wrapper 暴露给 Slicer。

## BF-09：所有协议都强制使用 UDP 风格分片

- 严重度：P2/实验风险
- 证据：代码确认

TCP、WebSocket 和 UDP 都经过同一个 `Slicer`。因此比较协议时，不仅传输协议发生变化，应用层分片数量、发送调用数量以及 pacing 行为也被绑定进实验。TCP 本来具备字节流能力，但当前仍被拆成 19 KB Corelink message。

这不是必然的功能 bug，却会影响论文中“协议因素”的解释。

## BF-10：Reassembler 对重复分片静默覆盖

- 严重度：P2
- 证据：代码确认

同一个 `(frame, sequence)` 再次到达时直接覆盖旧 payload。若两份 payload 不同，没有 warning、counter 或 frame invalidation。诊断时无法区分网络重复包与内部接收 buffer 损坏。

## BF-11：从 Corelink I/O thread 直接操作 ROS publisher 和日志状态

- 严重度：P2
- 证据：潜在并发问题
- 位置：`BridgeNode::onCorelinkMessage`

Corelink 回调不在 ROS executor thread。代码直接更新：

- `m_reassembler`；
- 诊断 histogram/counter；
- `m_local_publisher`。

如果 Corelink 保证每 channel 单线程回调，当前状态可能安全；但 UDP 重复 receive、I/O concurrency level 或未来多 channel 会打破这个假设。需确认 callback serialization，或用 TSan 验证。

## BF-12：pacing 参数负值/队列参数负值没有验证

- 严重度：P2
- 证据：代码确认
- 位置：`BridgeNode` 构造函数

`send.pacing_queue_max` 从 signed int 直接 cast 到 `size_t`。负值会变成极大的正数，取消预期的内存保护。`topic.max_rate` 的负值被当作关闭限速；`qos` depth、port 范围也缺少显式验证。

## BF-13：连接或认证失败后节点保持存活但不工作

- 严重度：P2
- 证据：代码确认
- 位置：`BridgeNode` 构造函数中的 `connect` callback

失败时只记录 `RCLCPP_FATAL` 并 `return`。ROS 节点继续 spin，没有退出、重试或对外 health 状态。Kubernetes/Docker 会认为进程健康，实验则可能得到全零 receiver 数据。

## BF-14：断线后没有重连与流恢复

- 严重度：P1/P2
- 证据：代码确认；代码注释也承认

control/data channel drop 后没有状态切换、重连或重新订阅。长时间 rosbag sweep 中一次短暂断线可能让后续全部样本失效，却没有明确的 run failure signal。
