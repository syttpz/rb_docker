# ROS 2 边缘卸载与 RTAB-Map 传输优化论文完整规划

> 项目方向：面向资源受限移动机器人的多模态 ROS 2 边缘卸载——基于分片、选择性压缩与网络自适应的实时传输优化
>
> 英文暂定题目：*Network-Adaptive Multimodal ROS 2 Transport for Energy-Efficient Edge-Offloaded Visual SLAM*
>
> 文档日期：2026-08-07

## 1. 总体判断

当前方向可以保留，但论文不应只写成“把 ROS 2 图像通过 Corelink 传输，然后比较 UDP、TCP 和地图效果”。单纯比较协议或压缩率，研究问题偏弱，而且当前系统还存在会污染实验结果的实现与测量问题。

论文应当围绕一个完整问题展开：

1. 如何可靠传输 RGB、Depth、CameraInfo、Odom 和 TF 等相互关联的 ROS 2 多模态数据；
2. 如何在带宽、延迟、CPU 和功耗约束下选择压缩方式、帧率、分片与 pacing 策略；
3. 这些传输策略最终如何影响 RTAB-Map 的实时性、可用 RGB-D 帧率、轨迹精度和地图质量。

Zstd、UDP/TCP、分片、功耗和 MATLAB 分析都应作为这一主线中的组成部分，而不是彼此独立的小实验。

## 2. 当前仓库状态

### 2.1 已经具备的功能

- ROS 2 Generic Subscription/Publisher 桥接；
- Corelink UDP、TCP 和 WebSocket 通道；
- 大消息应用层分片，当前最大 fragment payload 为 16 KB；
- fragment pacing 和发送队列上限；
- 初步 RealSense UDP/TCP benchmark；
- RGB、Depth、CameraInfo、TF、Odom 和 Battery 等 topic 的 rosbag 录制脚本；
- RTAB-Map 数据库保存和地图导出脚本；
- Docker 与 Kubernetes 部署雏形。

### 2.2 正式实验前必须解决的问题

1. 当前处于 `zstd` 分支，但 Zstd 没有真正接入桥接管线：
   - `compression.cpp` 没有加入 CMake target；
   - 声明与实现不一致；
   - 当前代码不可编译；
   - 发送端没有压缩，接收端没有解压；
   - 当前实际传输仍然是原始 CDR 加应用层分片。
2. Reassembler 只检查分片数量，没有确认 `0...last_seq` 每个 sequence 都存在，可能把缺片数据错误地当作完整帧。
3. Corelink UDP receiver 存在重复异步接收、共享 buffer 覆盖和错误累积 datagram 的风险。
4. 当前 benchmark 没有按统一的 `run_id/topic_id/frame_id` 配对，发送端和接收端观察窗口也未严格同步。
5. 当前单向延迟依赖两台机器的 wall clock，NTP/PTP offset 会直接进入结果。
6. Dockerfile 固定 clone 远端 `fragment` 分支，容器运行的代码可能不是当前实验代码。
7. Kubernetes/offload 配置还没有真正启动完整的 RTAB-Map 处理管线。
8. 已有 TCP “900 帧发送、3 帧收到”的结果更可能是 TCP framing 实现问题，暂时不能作为 TCP 性能结论。

因此，正式论文实验开始前，需要先完成测量基础设施和传输正确性阶段。

## 3. 论文研究问题

### RQ1：不同 ROS 2 topic 的压缩收益是否相同？

预期不同 topic 应使用不同策略：

| Topic | 候选策略 |
|---|---|
| Raw RGB | JPEG quality 50/70/85/95，或 Zstd 对照 |
| JPEG RGB | 通常不再使用 Zstd |
| Raw aligned depth | Zstd 1/3/6，或 `compressedDepth` |
| PNG/CompressedDepth | 测试后决定是否再压缩 |
| CameraInfo | 不压缩 |
| TF/Odom | 不压缩，优先低延迟 |
| TF static | 不压缩，可靠发送或周期重发 |

论文目标不是证明“Zstd 总是好”，而是证明按 topic 选择 codec 比全局统一压缩更合理。

### RQ2：分片大小、pacing 和网络条件如何影响整帧完成率？

若单个分片丢失概率为 \(p\)，一帧被拆成 \(n\) 个分片，在近似独立条件下，整帧成功率为：

\[
P_{frame}=(1-p)^n
\]

整帧丢失率为：

\[
P_{loss}=1-(1-p)^n
\]

例如 921 KB 的 RGB raw frame 按 16 KB 分片，大约产生 58 个分片。即使单片丢失率只有 0.1%：

\[
P_{loss}=1-(0.999)^{58}\approx5.64\%
\]

因此压缩不仅节省带宽，也通过减少分片数提高整帧成功率。

### RQ3：网络退化怎样影响 RGB-D 同步和 RTAB-Map？

RTAB-Map 依赖的是关联输入，而不是孤立 RGB frame。定义 RGB 与匹配 Depth 的时间偏差：

\[
\Delta t_{sync,i}=|t_i^{RGB}-t_{j(i)}^{Depth}|
\]

如果：

\[
\Delta t_{sync,i}>\tau_{sync}
\]

即使 RGB 和 Depth 都分别传输成功，这一组数据仍可能无法被 RTAB-Map 使用。因此消息 delivery rate 高并不等于 SLAM usable-frame rate 高。

### RQ4：能否根据网络和计算状态自动选择传输策略？

系统状态可以表示为：

\[
s_t=[B_t,RTT_t,J_t,L_t,Q_t,U_t^{CPU},P_t]
\]

其中分别表示可用带宽、RTT、抖动、丢失率、队列长度、CPU 利用率和功耗。

动作可以表示为：

\[
a_t=[f_{RGB},f_D,c_{RGB},c_D,z,q,g]
\]

其中分别表示 RGB/Depth 帧率、RGB/Depth codec、Zstd level、JPEG quality 和 pacing gap。

优化目标：

\[
\max_a\quad w_qQ_{map}-w_lL_{95}-w_eE-w_dD_{sync}
\]

约束：

\[
R_{tx}(a)\le B_t
\]

\[
L_{95}(a)\le L_{max}
\]

\[
U^{CPU}(a)\le U_{max}
\]

项目初期不使用强化学习。优先实现可解释的规则型或查表型控制器：

- 网络良好：较高分辨率和较低压缩；
- 带宽下降：先降低 RGB JPEG quality；
- 带宽继续下降：降低 RGB 帧率；
- 尽量保留 Depth 和 Odom；
- 队列积压时丢弃旧帧，避免延迟无限增长；
- Zstd 只对离线 profiling 证明有收益的 topic 启用。

## 4. 下周 rosbag 采集计划

下周的主要目标不是直接完成所有网络实验，而是采集一套不可变、可重复使用的原始数据集。之后所有算法和网络条件必须重放同一份 bag，才能公平比较。

### 4.1 路线设计

建议至少录制三类路线，每条路线 8–12 分钟，每类最好重复两次。

#### Bag A：简单验证路线

- 走廊或单个房间；
- 缓慢直线；
- 1–2 次转弯；
- 最后回到起点；
- 光照稳定；
- 用于验证整个 pipeline。

#### Bag B：主要实验路线

- 多次转弯；
- 包含高纹理与低纹理区域；
- 包含远近物体；
- 至少一次完整 loop closure；
- 作为论文主要数据集。

#### Bag C：压力路线

- 相对较快运动；
- 急转；
- 局部遮挡；
- 重复纹理或白墙；
- 明暗变化；
- 用于测试网络退化时 SLAM 的鲁棒性。

最好在地面标记固定起点和终点，让机器人最后返回同一物理位置，以便计算闭环漂移代理指标。

### 4.2 rosbag 必录 topics

必须录制：

```text
/camera/camera/color/image_raw
/camera/camera/aligned_depth_to_color/image_raw
/camera/camera/color/camera_info
/camera/camera/aligned_depth_to_color/camera_info
/odom
/tf
/tf_static
/cmd_vel
/battery_state
```

如果实际存在，再录制：

```text
/imu
/wheel_ticks
/wheel_vels
/wheel_status
/slip_status
/kidnap_status
/diagnostics
/rosout
```

如果磁盘空间允许，同时录制：

```text
/camera/camera/color/image_raw/compressed
/camera/camera/aligned_depth_to_color/image_raw/compressedDepth
```

Raw RGB 和 raw depth 必须保留，因为它们可以在离线阶段生成不同 JPEG、PNG、CompressedDepth 或 Zstd 版本。如果只录制已经压缩的数据，后续无法公平测试其他 codec。

### 4.3 同步记录系统资源

Pi 上至少每秒记录一次：

- wall-clock 和 monotonic timestamp；
- CPU 总利用率和各核利用率；
- CPU frequency；
- CPU temperature；
- 内存与 swap；
- bridge 进程 CPU/RSS；
- RTAB-Map 进程 CPU/RSS；
- 网络 TX/RX bytes；
- UDP error/drop counters；
- Docker image digest；
- git commit；
- ROS 参数文件；
- ROS topic、type、频率和 QoS 摘要。

建议采样频率：

- CPU、内存、温度：1–2 Hz；
- 网络统计：2–10 Hz；
- bridge 内部 counter：逐帧累计，每 1 秒输出一次摘要。

### 4.4 功耗记录

功耗值得测，而且可以成为论文的重要系统指标，但必须区分整机功耗和计算平台功耗。

#### 整机功耗

`/battery_state` 应当录制，但它可能存在采样率低、精度有限等问题，而且包含电机、相机、Pi 等全部负载。它适合回答“边缘卸载是否改善整机续航”，不适合精确比较 Zstd level 1 与 level 3 的计算功耗差异。

#### Pi 计算平台功耗

最好使用可导出 CSV 的 USB 功率计、INA219/INA226 或电源分析仪，记录：

- timestamp；
- voltage；
- current；
- power；
- cumulative energy。

推荐采样 20–50 Hz，最低不少于 10 Hz。

总能耗：

\[
E=\int_{t_0}^{t_1}P(t)\,dt
\]

平均功率：

\[
\bar P=\frac{E}{t_1-t_0}
\]

单位有效帧能耗：

\[
E_{frame}=\frac{E}{N_{usable}}
\]

如果下周还没有外部功率计，不需要推迟 rosbag 采集。先录 `/battery_state` 和系统资源，正式功耗实验可在后续使用 bag replay，让机器人保持静止，从而避免电机功耗干扰。

### 4.5 时间同步信息

跨机器实验前后保存：

```bash
timedatectl
chronyc tracking
chronyc sources -v
```

正式实验建议：

- Pi 和 edge/server 都使用 chrony；
- 每个 run 保存 clock offset；
- 单向延迟结果注明同步误差；
- 同时记录 RTT，作为不依赖绝对时钟的辅助指标。

### 4.6 每个 bag 的 manifest

每个 bag 目录应生成 manifest，至少包含：

- `run_id`；
- 日期、地点和路线编号；
- bag SHA-256；
- git commit；
- Docker image digest；
- 相机型号与序列号；
- 分辨率、FPS、exposure；
- topic、type、count 和频率；
- bag duration；
- ROS_DOMAIN_ID；
- TF tree 摘要；
- 相机到 base 的外参；
- 平均运动速度；
- 是否发生碰撞、暂停、相机掉线；
- 操作备注。

### 4.7 现场物理信息

同步保存：

- 路线草图；
- 起终点位置；
- 路线长度；
- 场地长宽；
- 若干地面标志或 landmark 的实测距离；
- 相机安装高度和角度；
- 光照条件；
- 是否有人经过；
- 一段手机视频，用于解释异常。

如果可行，可以放置 AprilTag 或测量 4–8 个 landmark，为地图几何质量提供基本 ground truth。

### 4.8 现场检查表

- [ ] 相机 RGB 和 aligned depth 均稳定发布；
- [ ] CameraInfo 存在且内参正确；
- [ ] `/odom` 时间戳连续；
- [ ] `/tf` 和 `/tf_static` tree 连通；
- [ ] 相机外参已经实测，不再使用估算值；
- [ ] 磁盘空间足够；
- [ ] 系统资源 logger 已启动；
- [ ] 功率记录设备已启动并对时；
- [ ] `run_id` 已写入 bag 和外部日志；
- [ ] 记录路线编号和开始时间；
- [ ] 结束后执行 `ros2 bag info`；
- [ ] 检查所有必需 topic 的 count 和频率；
- [ ] 立即备份原始 bag；
- [ ] 对原始 bag 设置只读或建立不可修改副本；
- [ ] 用短 replay 验证 RTAB-Map 可以读取。

## 5. Zstd 决策与实现

### 5.1 是否做 Zstd

结论：做，但仅作为选择性压缩策略中的一个组件，不把整篇论文押在 Zstd 上。

### 5.2 离线 profiling 输入

分别测试：

1. raw RGB；
2. JPEG RGB；
3. raw aligned depth；
4. CompressedDepth/PNG；
5. 整条 ROS serialized CDR；
6. CameraInfo/Odom/TF。

Zstd levels 第一轮只测试：

```text
off, 1, 3, 6, 9
```

不要一开始穷举 1–22。高 level 在实时机器人中通常收益有限、CPU 成本较高。

### 5.3 压缩指标

压缩比：

\[
CR=\frac{S_{raw}}{S_{compressed}}
\]

空间节省率：

\[
Saving=1-\frac{S_{compressed}}{S_{raw}}
\]

压缩吞吐：

\[
T_c=\frac{S_{raw}}{t_c}
\]

解压吞吐：

\[
T_d=\frac{S_{raw}}{t_d}
\]

压缩对端到端时间的近似净收益：

\[
G=\frac{S_{raw}-S_{compressed}}{B}-(t_c+t_d)
\]

只有当 \(G>0\) 时，压缩才真正降低端到端时延。

### 5.4 预期策略

- JPEG 后再次 Zstd：预计关闭；
- raw RGB：可做对照，但 JPEG 预计更有效；
- raw Depth：Zstd level 1 或 3 很可能值得；
- CameraInfo、Odom 和 TF：关闭压缩；
- 使用 frame checksum 检测应用层重组损坏。

### 5.5 正确的数据路径

必须先对完整 frame 压缩，再分片：

```text
ROS CDR
  -> frame compression
  -> frame metadata/checksum
  -> fragmentation
  -> Corelink
  -> reassembly
  -> checksum verification
  -> decompression
  -> ROS publish
```

不要逐 fragment 单独压缩，否则压缩比更差，也无法利用整帧相关性。

## 6. 传输协议改造

### 6.1 Frame protocol

当前 9-byte fragment header 应升级为明确的版本化协议，至少包含：

```text
magic
version
run_id
sender_id
topic_id
frame_id
source_timestamp
codec
original_size
compressed_size
fragment_index
fragment_count
frame_crc32
payload
```

必须具备：

- magic 和 version；
- sender/topic identity；
- 64-bit frame ID；
- fragment index/count；
- 原始长度和压缩后长度；
- codec；
- source timestamp；
- CRC32 或等效完整性校验；
- reassembly timeout；
- 每帧和全局内存上限。

### 6.2 发送端 counters

- ROS messages received；
- rate-limit dropped；
- compression success/failure；
- raw/compressed bytes；
- fragments generated；
- pacing queue dropped；
- Corelink send errors；
- compression time；
- queue waiting time。

### 6.3 接收端 counters

- fragments received；
- duplicate fragments；
- invalid headers；
- checksum failures；
- incomplete-frame timeouts；
- reassembly successes；
- decompression failures；
- ROS publish count；
- per-frame end-to-end latency。

### 6.4 数据损失归因链

按 frame ID 跟踪完整路径：

```text
source frame
  -> rate-limit drop
  -> compression failure/drop
  -> pacing queue drop
  -> transport loss
  -> reassembly timeout
  -> checksum/decompression error
  -> ROS publish
  -> RGB-D synchronization
  -> RTAB-Map processed
```

这条损失路径可以成为论文的重要系统图和结果表。

### 6.5 TCP 的定位

TCP 应保留为 baseline，但顺序必须是：

1. 修复 TCP byte-stream framing；
2. 用固定 1 KB、16 KB、64 KB 合成消息测试；
3. 长时间验证无卡顿、无错帧；
4. 再与 UDP 比较；
5. 最后才运行真实相机和 RTAB-Map。

在 TCP framing bug 修复前，现有结果不能用于证明 TCP 不适合图像传输。

FEC 暂时作为 future work。除非后续实验确认 UDP fragment loss 是主要瓶颈，否则不优先实现。

## 7. 实验设计

避免所有变量的全笛卡尔积，采用分阶段筛选。

### 实验 0：传输正确性

不运行 RTAB-Map，只验证协议和桥接。

消息大小：

```text
1 KB, 16 KB, 64 KB, 300 KB, 1 MB
```

发送频率：

```text
1, 5, 15, 30 Hz
```

网络条件：

```text
0%, 1%, 5%, 10% loss
```

验证项目：

- [ ] 发送和接收内容逐字节一致；
- [ ] CRC 一致；
- [ ] 乱序输入可以正确重组；
- [ ] 缺片不会被接受；
- [ ] 缺片 frame 会超时清理；
- [ ] duplicate 可以识别；
- [ ] 异常超大 sequence 被拒绝；
- [ ] sender 重启不会与旧 frame 混合；
- [ ] 两个 sender 不会串帧；
- [ ] 内存占用存在硬上限；
- [ ] 长时间运行无持续内存增长。

### 实验 1：离线压缩 profiling

从同一个 bag 抽取约 1,000 帧 RGB 和 Depth，测试：

- JPEG quality：50、70、85、95；
- Zstd level：off、1、3、6、9；
- CompressedDepth；
- RGB 和 Depth 分别压缩；
- 整条 CDR 压缩作为对照。

输出：

- 压缩比；
- 压缩/解压时间；
- CPU 利用率；
- 平均功率和能耗；
- JPEG PSNR/SSIM；
- 压缩后 fragment count；
- 预计传输时间和整帧成功率。

这一阶段用于筛掉无效配置。

### 实验 2：纯网络传输性能

使用同一个 bag replay，先不运行 RTAB-Map，或者单独记录 RTAB-Map 输入。

建议使用 `tc netem` 设置网络条件：

| 场景 | 带宽 | 延迟/RTT | Loss |
|---|---:|---:|---:|
| N0 | 不限 | 基础网络 | 0% |
| N1 | 20 Mbps | 20 ms | 0% |
| N2 | 10 Mbps | 40 ms | 0.5% |
| N3 | 5 Mbps | 80 ms | 1% |
| N4 | 2 Mbps | 120 ms | 3% |
| N5 | 动态变化 | 20–120 ms | 0–3% |

每种配置至少重复 5 次，并随机化运行顺序。

记录：

- goodput；
- frame completion ratio；
- p50/p95/p99 latency；
- jitter；
- queue occupancy；
- incomplete frames；
- synchronized RGB-D rate；
- CPU 和内存；
- power；
- energy per delivered/usable frame。

### 实验 3：RTAB-Map 端到端实验

只选择前两阶段最有代表性的 5–7 种配置：

1. Local RTAB-Map，不经过网络；
2. Offload + raw + UDP fragmentation；
3. Offload + JPEG RGB + raw depth；
4. Offload + JPEG RGB + Zstd depth；
5. Offload + TCP；
6. Offload + 固定保守策略；
7. Offload + adaptive strategy。

每个 bag、每种配置至少重复 5 次。

固定条件：

- 相同 bag；
- 相同 replay rate；
- `use_sim_time=true`；
- 相同 RTAB-Map 参数；
- 固定随机性或确定性设置；
- 每次使用新的数据库；
- 固定 CPU governor；
- 固定 Docker image digest；
- 固定 bridge commit 和配置文件。

## 8. 评价指标

### 8.1 网络指标

帧完成率：

\[
FCR=\frac{N_{complete}}{N_{source}}
\]

有效吞吐：

\[
Goodput=\frac{\sum S_{published}}{T}
\]

带宽效率：

\[
\eta=\frac{ROS\ useful\ bytes}{wire\ bytes}
\]

端到端延迟：

\[
L_i=t_i^{publish}-t_i^{source}
\]

必须报告 median、p95 和 p99，不只报告平均值。

### 8.2 RGB-D 同步指标

RGB-D 可用率：

\[
SR=\frac{N_{matched\ RGBD}}{N_{source\ RGB}}
\]

同步偏差：

\[
\Delta t_i=|t_i^{RGB}-t_{j(i)}^{Depth}|
\]

### 8.3 能耗指标

离散采样下：

\[
E=\sum_kP_k\Delta t
\]

单位有效帧能耗：

\[
E_{frame}=\frac{E}{N_{usable}}
\]

如果映射面积可以可靠估计，可增加：

\[
E_{map}=\frac{E}{A_{mapped}}
\]

### 8.4 SLAM 和地图指标

如果有 ground truth：

- ATE RMSE；
- RPE translation/rotation；
- endpoint drift；
- loop closure precision/recall。

如果没有 mocap：

- 与 local baseline 轨迹对齐后的差异；
- 起终点闭环漂移；
- RTAB-Map processed nodes；
- accepted/rejected loop closures；
- optimization residual；
- map point count；
- cloud-to-cloud distance；
- occupancy-grid IoU；
- map coverage。

轨迹对齐后的 ATE：

\[
ATE_{RMSE}=\sqrt{\frac{1}{N}\sum_{i=1}^{N}\|\mathbf p_i^{gt}-(\mathbf R\mathbf p_i+\mathbf t)\|^2}
\]

Occupancy IoU：

\[
IoU=\frac{|M_{test}\cap M_{ref}|}{|M_{test}\cup M_{ref}|}
\]

### 8.5 延迟分解

\[
L=L_{encode}+L_{queue}+L_{tx}+L_{network}+L_{reassembly}+L_{decode}+L_{sync}+L_{SLAM}
\]

每一阶段都应尽可能有独立 timestamp 或 counter，避免把所有延迟统称为“网络延迟”。

## 9. MATLAB 分析计划

MATLAB 不参与实时 ROS 管线，主要用于离线统计、建模和生成论文图。

### 9.1 建议目录

```text
analysis/
  import_runs.m
  pair_frames.m
  compute_transport_metrics.m
  compute_energy.m
  analyze_compression.m
  analyze_sync.m
  analyze_slam.m
  fit_models.m
  plot_figures.m
  configs/
  tables/
  figures/
```

每个实验 run 输出：

```text
manifest.json
frames.csv
resource.csv
power.csv
rtabmap_stats.csv
trajectory.csv/tum
map_metrics.json
```

### 9.2 按 ID 配对 frame

不能使用表格行号配对，也不能只比较消息总数。

```matlab
paired = innerjoin(sourceTable, receiverTable, ...
    'Keys', {'run_id','topic_id','frame_id'});
```

查找丢失 frame：

```matlab
allFrames = outerjoin(sourceTable, receiverTable, ...
    'Keys', {'run_id','topic_id','frame_id'}, ...
    'MergeKeys', true);
```

### 9.3 置信区间

每组至少 5 个独立 run。以 run 为统计单位，不能把数千个 frame 当作数千次独立实验。

```matlab
ci = bootci(10000, @mean, runMetrics);
```

报告：

- mean 与 95% CI；
- median；
- p95；
- effect size；
- 必要时使用 ANOVA 或 Kruskal-Wallis。

### 9.4 回归模型

端到端延迟模型：

\[
L=\beta_0+\beta_1S_c+\beta_2N_f+\beta_3Q+\beta_4RTT+\beta_5B^{-1}+\epsilon
\]

MATLAB 示例：

```matlab
mdl = fitlm(tbl, ...
    'latency_p95 ~ compressed_bytes + fragment_count + queue_mean + rtt + inv_bandwidth');
```

Frame 成功率可以使用 logistic regression：

```matlab
mdl = fitglm(tbl, ...
    'completed ~ fragment_count + loss_rate + queue_mean + protocol', ...
    'Distribution', 'binomial');
```

### 9.5 论文图表

计划生成：

1. 系统架构图；
2. frame protocol 和数据路径图；
3. 不同 topic 的压缩比与压缩时间；
4. fragment count 与整帧成功率；
5. 网络条件与 p95 latency；
6. 网络条件与 RGB-D usable rate；
7. CPU/功耗与压缩策略；
8. 网络指标与 ATE/地图 IoU；
9. 固定策略与 adaptive 策略对比；
10. 地图和轨迹可视化对比。

## 10. 论文结构

### Chapter 1：Introduction

- 移动机器人本地计算资源受限；
- 边缘卸载需要传输高带宽、多模态、时序关联数据；
- 通用 ROS bridge 只保证消息传递，不保证 SLAM 可用性；
- 研究问题与贡献。

建议贡献表述：

1. 一个具备完整性验证、分片重组和逐层可观测性的 Corelink ROS 2 大消息传输层；
2. 一个面向 RGB-D SLAM 的 topic-aware 选择性压缩与同步感知策略；
3. 一套从网络性能、计算能耗到 RTAB-Map 地图质量的端到端实验评估。

### Chapter 2：Background and Related Work

- ROS 2/DDS；
- cloud/edge robotics；
- RGB-D/visual SLAM；
- image/depth compression；
- unreliable network and fragmentation；
- computation offloading。

### Chapter 3：System Design

- Robot–Corelink–Edge 架构；
- frame protocol；
- fragmentation/reassembly；
- compression selection；
- instrumentation；
- adaptive controller。

### Chapter 4：Mathematical Model

- 压缩比和压缩时间；
- fragment completion probability；
- latency decomposition；
- energy model；
- constrained optimization。

### Chapter 5：Experimental Methodology

- 硬件与软件；
- rosbag 数据集；
- 网络模拟；
- baseline；
- 参数；
- metrics；
- repetitions；
- statistical method。

### Chapter 6：Results

1. 压缩 profiling；
2. 传输性能；
3. 能耗；
4. RGB-D 同步；
5. SLAM/map；
6. adaptive 策略；
7. 消融实验。

### Chapter 7：Discussion and Conclusion

- 什么条件下 Zstd 有用；
- 为什么 delivery rate 不等于 SLAM usable rate；
- 时钟同步和测量误差；
- Corelink 特定限制；
- 外部有效性；
- FEC、priority transport 和更复杂控制器作为 future work。

## 11. 执行时间表

### 阶段 1：本周——确保下周可以采集有效数据

- [ ] 修正并验证 rosbag topic；
- [ ] 增加 bag manifest；
- [ ] 增加系统资源 logger；
- [ ] 检查 `/battery_state` 字段和频率；
- [ ] 检查 TF tree；
- [ ] 检查 Odom timestamp；
- [ ] 实测相机外参；
- [ ] 做 2 分钟试录；
- [ ] 自动运行 `ros2 bag info`；
- [ ] replay 试录 bag 并验证 RTAB-Map；
- [ ] 准备路线图和现场 checklist。

### 阶段 2：下周——正式采集 rosbag

- [ ] A/B/C 三类路线；
- [ ] 每类重复两遍；
- [ ] 每遍 8–12 分钟；
- [ ] 保留完整 raw RGB/depth；
- [ ] 记录资源、功耗和时间同步；
- [ ] 每次结束立即检查 topic count；
- [ ] 备份并冻结原始 bag。

### 阶段 3：随后 1–2 周——传输正确性

按优先级：

1. Reassembler 缺片完整性；
2. versioned header 和 CRC；
3. timeout 与内存上限；
4. sender/topic identity；
5. Corelink UDP receive；
6. async send buffer lifetime；
7. 逐层 counters；
8. paired benchmark；
9. TCP framing；
10. 容器版本固定。

### 阶段 4：第 3 周——压缩 profiling

- [ ] 从 bag 提取 RGB/Depth 样本；
- [ ] 测试 JPEG、CompressedDepth 和 Zstd；
- [ ] 记录时间、CPU、功耗和压缩比；
- [ ] 根据结果筛选 codec 和参数。

### 阶段 5：第 4–5 周——接入选择性压缩

- [ ] Zstd frame codec；
- [ ] JPEG/CompressedDepth 配置；
- [ ] codec metadata；
- [ ] checksum；
- [ ] compression timing；
- [ ] raw/compressed byte counters。

### 阶段 6：第 6 周——网络实验

- [ ] 合成消息正确性；
- [ ] bag replay；
- [ ] `tc netem` 网络条件；
- [ ] 固定策略实验；
- [ ] 每组至少 5 次；
- [ ] 自动导出 CSV/JSON。

### 阶段 7：第 7 周——RTAB-Map 实验

- [ ] local baseline；
- [ ] network baseline；
- [ ] fixed optimized strategy；
- [ ] adaptive strategy；
- [ ] trajectory/map metrics。

### 阶段 8：第 8 周——MATLAB 与论文结果

- [ ] 数据清洗；
- [ ] 置信区间；
- [ ] 回归模型；
- [ ] 图表；
- [ ] 异常 run 判定；
- [ ] 消融实验；
- [ ] 完成 Results 初稿。

## 12. 范围控制

### 必须完成

- 高质量、可重放 rosbag；
- 功耗、CPU、网络与同步信息记录；
- 分片正确性；
- frame ID 配对；
- RGB-D 同步指标；
- JPEG RGB 与 Depth 压缩对比；
- RTAB-Map 端到端结果；
- MATLAB 统计和论文图表。

### 应该完成

- Zstd，重点测试 raw depth；
- 自适应帧率/压缩策略；
- UDP pacing；
- 修复后的 TCP baseline。

### 暂时不做

- 自研压缩算法；
- 神经网络压缩；
- 强化学习；
- 复杂 FEC；
- 大量传输协议；
- Zstd 1–22 全等级穷举；
- 只依靠肉眼比较地图。

## 13. 最终论文主线

先用不可变 rosbag 建立可重复输入，再把每一帧从采集、压缩、分片、网络、重组和 RGB-D 同步一直跟踪到 RTAB-Map。最终优化目标不是单一带宽，而是：

> 在给定网络、时延和能耗约束下，最大化可供 SLAM 使用的同步 RGB-D 数据率与最终地图质量。

这条主线能够把 Corelink、ROS 2、分片、Zstd、边缘卸载、RTAB-Map、功耗测量和 MATLAB 分析统一到同一个可验证的研究问题中。
