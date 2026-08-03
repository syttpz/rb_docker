# Experiment validity risks

这不是论文设计稿，而是说明当前工具链中哪些因素会让“传输因素导致地图质量变化”的结论无法可靠归因。

## EV-01：source/receiver 观察窗口没有按 frame 配对

当前 benchmark 在两台机器上分别运行固定时长 observer。已有 UDP JSON 的开始时间相差约 3 秒，TCP 也不是严格同步窗口。因此：

```text
source count - receiver count
```

不能精确等同于网络丢帧数。窗口边界本身就会包含不同帧。

更可靠的方法是记录稳定的 run ID、stream ID、frame ID、source timestamp，并在离线阶段按 ID join。

## EV-02：延迟依赖跨机器 wall clock

脚本用 `time.time() - header.stamp`。这要求 sender/receiver 与相机时间源严格同步。NTP offset/drift 会直接进入延迟值，甚至可能被误认为 Corelink 延迟或抖动。

每次实验至少应记录两端 clock offset；更稳妥的是加入回环测量或使用同一 monotonic 时间域能够解释的协议时间戳。

## EV-03：当前 size 只统计 `msg.data`

benchmark 对带 `data` 字段的图像近似统计 payload，但不包含：

- ROS serialization/header 字节；
- 分片 9 字节头；
- Corelink 8 字节头和 JSON header；
- IP/UDP/TCP/WebSocket 开销；
- 重传。

所以现有 `bandwidth_Bps` 是 ROS payload throughput，不是链路占用。论文中应明确指标名称。

## EV-04：传输变量和应用层行为耦合

切换 TCP/UDP 时，Corelink 内部 framing、socket manager 行为不同；bridge 仍执行相同 19 KB 分片，而 pacing、queue drop、ROS QoS 又能改变到达序列。

比较协议前必须记录并固定：

- bridge commit/image digest；
- topic QoS；
- fragment payload；
- pacing 和 queue cap；
- source rate cap；
- 图像编码、分辨率、quality；
- RTAB-Map 参数和随机性；
- rosbag replay rate 和 `/clock` 设置。

## EV-05：bridge 内部 drop 与网络 drop 不可区分

目前可能丢数据的位置包括：

- `topic.max_rate` 主动跳过；
- pacer queue 满时整帧 drop；
- Corelink MTU 拒绝；
- UDP/socket drop；
- Reassembler stale eviction；
- ROS subscription/publisher QoS queue；
- RTAB-Map 同步器丢弃无法配对的 RGB/depth/info。

如果只比较最终消息数，这些都会被错误统称为“网络丢包”。每层需要独立 counter。

## EV-06：RGB、depth、camera_info 和 TF 是关联输入

RTAB-Map 不是只消费 RGB topic。offload 至少需要保持：

- RGB；
- depth；
- camera info；
- TF/static TF；
- 可能还有 odometry。

分别桥接时，每条流的延迟/丢失会改变跨 topic 同步成功率。最终地图变差可能来自同步失败，而不是单张图像质量下降。这本身可以成为论文变量，但必须观测同步器 drop 数和时间差分布。

## EV-07：rosbag 必须作为不可变输入数据集

为了反复测试，应先验证 bag 确实包含所有目标 topic、消息数、频率和时间范围。当前 `startmapping.sh` 的 compressed topic 拼写错误说明仅凭脚本退出成功不够。

建议每个 bag 保存 manifest：文件 hash、topic/type、count、duration、相机参数、TF tree 摘要。

## EV-08：地图质量需要独立 ground truth 或稳定代理指标

仅比较导出 PLY 大小或“看起来好不好”不足以支持结论。可按数据条件选择：

- 有 ground truth：ATE、RPE、尺度漂移；
- 同一 bag 重复实验：轨迹与 baseline 的相对偏差；
- 图优化：接受/拒绝的 loop closure 数、优化残差；
- 地图：点数、覆盖率、cloud-to-cloud distance、occupancy IoU；
- 系统：RTAB-Map processed/dropped frames、同步失败、运行时间与资源消耗。

在 Corelink 和分片 P0 问题修复前，不建议采集正式论文数据；当前结果适合用于 bug reproduction 和系统调试。
