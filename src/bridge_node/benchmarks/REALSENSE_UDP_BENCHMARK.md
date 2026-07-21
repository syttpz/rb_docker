# RealSense 图像传输 benchmark(UDP,附 TCP 对照)

测试日期:2026-07-21。机器人 Pi(D435 相机,`docker compose` 容器,domain 0)
通过 `corelink.hpc.nyu.edu` 转发到笔记本(domain 2),`Testuser` 账号,
`Chalktalk` workspace。用的是 `benchmark_topic_bridge.py`(见同目录),在 hop
两端各跑一份 observer,对比消息数/字节数/延迟算出丢失率、带宽、延迟增量。

三组测试,原始数据在 `results/`:

| 场景 | 分辨率/编码 | 协议 | 结果文件 |
|---|---|---|---|
| A. 原始帧 | 640x480 RGB8, ~0.92MB/帧 | UDP | 无 JSON(发送端直接报错,见下) |
| B. 压缩帧 | 424x240 JPEG, ~17.6KB/帧 | UDP | `compressed_424x240_udp_{source,receiver}.json` |
| C. 压缩帧 | 424x240 JPEG, ~17.6KB/帧 | TCP | `compressed_424x240_tcp_{source,receiver}.json` |

## A. 原始帧 + UDP:100% 失败,不是丢包,是直接被拒绝

`/camera/camera/color/image_raw`(640x480 RGB8,未压缩,921,672 字节/帧,15fps,
本地带宽实测 13.83 MB/s)配 `corelink.data_protocol: udp` 时,sender 端每一帧
都在 `send_data()` 调用后立刻收到 `on_error`:

```
[ros2_bridge_node] sender data channel 1 error: Unable to send data packet as
MTU for this channel is 20000, whereas attempted to pass 921674 bytes of data
excluding corelink headers.
```

**根因**:Corelink 给这个 UDP data channel 协商出的 MTU 上限是 **20000 字节**
(这是 corelink 服务器/协议层面的限制,不是 OS UDP 65507 字节上限,也不是网络
MTU)。任何超过这个数字的消息,`CorelinkTransport`/`bridge_node.cpp` 现在的
"raw CDR passthrough"设计(见 `HANDOFF.md`)会原样往下传给 corelink 库,
corelink 库直接在本地拒绝,连网络都没发出去。**丢失率是 100%,且是确定性的
(不是偶发丢包),只要消息超过这个 MTU,一帧都过不去。**

这条 20000 字节的 MTU 上限,后续在压缩帧测试里同样卡到过一次(见下)。

## B. 压缩帧(JPEG,~17.6KB)+ UDP:能跑通,丢失率低,延迟增加可控

先说明:默认分辨率(640x480)下压缩出来的 JPEG 平均 29.3KB,同样超过 20000 字节
MTU,同样 100% 失败(现象与 A 完全一致,只是数字从 921KB 变成 29KB,报错文本里
`MTU for this channel is 20000` 一样)。把相机改成 424x240(D435 支持的一档更低
分辨率,`jpeg_quality` 参数虽然能设置成功但对已经在跑的 image_transport 编码器
不生效,没能用它把 640x480 的图压小,只能换分辨率),平均帧大小 17.6KB,才落到
MTU 以内。以下数据基于 424x240、JPEG quality 95(默认值)。

30 秒窗口,source(相机本机话题)vs receiver(桥接之后本地重新发布的话题):

| 指标 | Source(桥接前) | Receiver(桥接后) | 差值 |
|---|---|---|---|
| 消息数 | 451 | 450 | **丢 1 帧,0.22%** |
| 速率 | 15.02 Hz | 14.99 Hz | 基本保持 |
| 平均帧大小 | 17,589 B | 17,593 B | 一致(桥接不改数据) |
| 带宽 | 264.1 KB/s | 263.8 KB/s | 基本保持 |
| 延迟(到达时刻 - header.stamp) | 66.0 ms(驱动自身编码流水线延迟,近似常数,stddev 0.08ms) | 80.7 ms(p95 82.2ms,max 123.0ms,stddev 2.79ms) | **corelink 这一跳大约加了 14.7ms 平均延迟,尾部最坏到 +57ms 左右** |
| 帧间隔抖动 | stddev 0.085ms(几乎是节拍器) | stddev 3.99ms,min 23ms / max 109ms | 桥接把稳定的 15fps 节奏打乱了,个别帧提前"扎堆"到达、个别帧延后到接近两帧间隔(对应丢的那 1 帧) |

**结论**:只要消息本身小于 corelink 协商出的 UDP MTU,这条路径工作正常——
丢失率低(0.22%,量级上跟普通局域网 UDP 差不多)、额外延迟不大(~15ms)、
带宽损耗几乎为零。真正的风险点是"消息多大能通过",不是"UDP 本身不可靠"。

## C. 压缩帧 + TCP:出现严重卡顿,不是"更可靠"的替代方案

同样 424x240 JPEG 数据,只换成 `corelink.data_protocol: tcp`,60 秒窗口:

| 指标 | Source | Receiver |
|---|---|---|
| 消息数 | 900(稳定 15Hz,全程无报错) | **3** |
| 帧间隔 | 66.7ms(稳定) | 平均 **7498ms**,最大 **10531ms** |

900 帧发出去,60 秒内只收到 3 帧,相当于 99.67% 的帧要么严重迟到、要么这个测试
窗口内根本没到。这**不是丢包**——TCP 不会静默丢数据,sender 端全程零报错,
说明数据确实按字节送到了服务器,问题出在 receiver 这端把数据从 TCP 字节流里
切分成一条条 Corelink 消息的环节上(`corelink_client.hpp` 里那段处理 TCP
"multi-part frame"/`incomplete_packet_buffer` 的重组逻辑,型式上专门只对 TCP
生效,UDP 走的是完全不同、简单得多的单包直传路径)。之前这个项目里 TCP 测试过
的场景(`/battery_state`、`/chatter`,≤1Hz)都很轻量,这是第一次拿一个持续
~15Hz、每帧十几 KB 的流去压 TCP 通道,直接暴露出问题——大概率是 corelink_cpp
库自身在持续高频场景下的一个新 bug(`CORELINK_PATCHES.md` 里已经记录过 3 个
类似的库自身缺陷,这可能是第 4 个),不是 corelink 服务器或者这份桥接代码
自己的逻辑问题,但没有进一步深挖根因(超出这次测试的时间预算)。

**结论:对于持续、较高频率的数据流(图像这类),TCP 目前不是比 UDP更可靠的
选择,反而更差——UDP 至少给出"丢失率低、延迟可预期"的老实结果,TCP 表现出的
是不可预测的长时间卡顿。**

## 怎么优化(不在这次改,先记录方向)

1. **最直接的问题是"消息超过 MTU 就 100% 失败",而不是当前代码有任何提示或降级
   处理**。现在的行为是:`on_error` 打一行 stderr 日志(这次测试专门为了能观察
   到才特意接上的,之前完全没接,见 `corelink_transport.cpp` 提交历史),没有
   任何机制告诉上层"这个 topic 类型/分辨率根本没法用这个协议桥"。可选方向,
   按实现代价从低到高:
   - **最省事**:文档/操作规范层面约束——UDP 桥接的 topic 一律必须是压缩过的
     (`.../compressed`,不能是 `image_raw`),而且要提前手动确认过压缩后单帧
     大小在 MTU 以内(这次是踩坑试出 424x240 才够小,可以做成一个固定推荐档位
     写进文档)。零代码改动,立刻能用,但很脆弱——换个场景/换个相机就得重新试。
   - **中等**:`BridgeNode`/`CorelinkTransport` 主动查询 UDP data channel 协商出
     的实际 MTU(创建 sender 时服务器应该会告知,或者从第一次失败的 on_error
     消息里解析出来),超过 MTU 直接在 `RCLCPP_FATAL` 里报出来并拒绝以
     `to_corelink` 模式启动这个 topic,而不是像现在这样默默地每帧都失败但节点
     还在正常运行、日志刷屏。至少让"配错了"这件事在启动时就暴露,而不是运行时
     悄悄地 100% 丢数据。
   - **最彻底**:在 `CorelinkTransport`/`onLocalMessage` 层加一层应用层分片/
     重组(大消息按 MTU 切成带序号的多个 chunk,receiver 端按序号攒齐再拼
     回原始字节)。这是唯一能让"任意大小的消息都能走 UDP"成立的办法,但要处理
     乱序到达、分片丢失怎么办(整帧丢弃?超时?)、以及每个 chunk 加多少字节
     的头部开销,工作量不小,值得先确认清楚这个项目实际是否真的需要"UDP 传输
     大消息"这个能力,再决定要不要做。

2. **UDP 场景下 0.22% 的丢失率和运行时抖动**,如果对下游(比如 rtabmap 离线跑
   建图)完全无所谓就不用管;如果在意,方向是:
   - 帧越小,丢失率理论上越低(这次 17.6KB 已经比 20000 字节上限留了不少余量,
     可以再往小调,换取更低丢失率/抖动,直接的时间/画质权衡)
   - 如果下游需要感知"丢了哪一帧"而不是静默跳过,需要在应用层加序号/时间戳
     (现在 CDR 原始透传完全没有这类元数据,丢帧对下游是完全不可见的)

3. **TCP 卡顿问题本身值得单独开一次调试**,不属于这次"看看 UDP 有没有问题"的
   范围,但既然测出来了记一笔:下次调试建议先脱离真实相机,用一个能精确控制
   消息大小/频率的合成测试(比如固定发送 18KB 的随机字节 payload,15Hz,持续
   几分钟),复现这个卡顿之后去单步/加日志跟 `corelink_client.hpp` 里 TCP 的
   `incomplete_packet_buffer` 重组逻辑,确认是不是文中怀疑的那个环节。
