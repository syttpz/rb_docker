# ros2_bridge_node 进度记录 / 交接文档

> 写这份文档最初是因为要换到另一台电脑重新手写一遍代码(为了真正理解,不是复制
> 粘贴)。这里记录"为什么"和"现在到哪一步了",代码本身不用抄这份文档里的片段,
> 去看实际源文件。**这个仓库现在是独立 git 仓库**(`bridge_node`,已推到
> `github.com:syttpz/bridge_node`),不再跟 `corelink-client-dev` 放一起——
> `corelink_cpp/` 是从 `corelink-client-dev/cpp/` 拷进来的一份带补丁的快照(自包含,
> 换机器直接 clone 这一个仓库就够,不用再拷 `corelink-client-dev`)。

## 这是在做什么、为什么

**研究背景**:机器人跑 ROS2(DDS),想让它跟一台跑 Docker ROS2 的远程服务器通信。
DDS 默认靠 UDP 组播发现,假设大家在同一个局域网,跨网络/NAT 场景下天然别扭。

**方案**:机器人和服务器内部各自的 ROS2 通信**完全不动**,还是原生 DDS。只在
"机器人 ↔ 服务器"这一跳,插一个桥接节点(`ros2_bridge_node`),把指定的
ROS2 topic 转发进 Corelink(NYU 的一个中心化多语言 pub/sub 平台),对面镜像跑一个
桥接节点收进来再发布回本地 ROS2 图。

**明确不做的事**:不写 `rmw` 实现(那是"完全替换 DDS"才需要的,我们只是接一段
额外的跨网传输,不改变 ROS2 应用代码的行为)。完整背景和架构图在
`/home/syttpz/.claude/plans/ros2-dds-plan-rmw-ethereal-fog.md`(这个文件路径是
写在这台机器上的,换电脑后这个具体路径不存在了,但内容值得整个抄一份过去)。

**为什么选 Corelink 而不是更成熟的 MQTT/Zenoh**:老实说,单纯解决"ROS2 跨网"这个
通用问题,Zenoh(有官方 `rmw_zenoh`)大概率更省事。选 Corelink 是因为:
1. 实验室已经有现成部署(`corelink.hsrn.nyu.edu`),不用自己搭
2. Corelink 的 data channel 可以按 stream 单独选协议(UDP/TCP/WebSocket),
   MQTT 主流部署是 TCP-only,这对允许丢包换低延迟的传感器数据流是个实打实的
   差异点,值得作为方法论章节的论据,而不是"Corelink 更好"这种空泛主张
3. 论文的贡献点应该落在 offloading 策略本身(RTAB-Map 节点卸载这条后续线),
   传输层选型是实现细节,不是论文的核心论点——这条是跟自己反复确认过的

## 现在的代码结构(已经写完、编译通过)

```
bridge_node/                          ← 独立仓库,根目录本身就是 ament_cmake 包
├── corelink_cpp/                     ← 从 corelink-client-dev/cpp/ 拷来的带补丁快照(打了3个补丁,见下)
├── include/ros2_bridge_node/
│   ├── corelink_transport.hpp        ← 包一层 corelink_classic_client,不认识 ROS2
│   └── bridge_node.hpp               ← rclcpp::Node 子类,唯一同时认识两边的地方
├── src/
│   ├── corelink_transport.cpp
│   ├── bridge_node.cpp
│   └── main.cpp                      ← rclcpp::init + spin
├── CMakeLists.txt                    ← 用 add_subdirectory(corelink_cpp) 把 corelink 库编进来
├── package.xml
├── config/
│   ├── robot_side.yaml               ← direction: to_corelink
│   └── server_side.yaml              ← direction: from_corelink,跟上面配对测试用
├── launch/bridge.launch.py
├── CORELINK_PATCHES.md               ← corelink cpp 库的 3 个编译补丁说明(中文)
└── build/                            ← cmake configure + build 产物,git 不追踪(见 .gitignore)

```

### 设计要点(手写的时候记得还原这些决定,不是随便选的)

1. **`CorelinkTransport` 和 `BridgeNode` 分两层**:前者只懂 Corelink API
   (`connect` / `createSender` / `createReceiver` / `sendData`,全是回调风格,
   包住了 Corelink 的异步 request/response 机制),完全不 include `rclcpp`。
   后者是唯一"双语"的地方。这样以后想换传输层,理论上只用换下层。

2. **一个 `BridgeNode` 实例 = 一个 topic + 一个方向**,不是一上来就做
   config 驱动的多 topic manager。这是刻意按"先跑通最小闭环,再泛化"的顺序来的
   (对应 plan 里的 incremental build order:先单 topic 单方向,再加反方向,
   再泛化成 YAML 配置多个)。

3. **消息透传用原始 CDR 字节,不做 JSON 转换**:两端都是 ROS2,所以用
   `rclcpp::GenericSubscription`/`GenericPublisher` 拿/发 `rclcpp::SerializedMessage`
   的原始字节,直接塞进 Corelink 的 `send_data()`/从 `on_receive` 里掏出来包回去。
   没有逐消息类型写 C++ struct,也没有 JSON 反序列化那一层。代价是两端必须有
   完全一致的消息类型定义(CDR 不是自描述的),而且这份数据对非 ROS2 的
   Corelink 客户端是不可读的二进制——这是刻意的简化,不是遗漏。

4. **顺序细节:`to_corelink` 方向要等 Corelink sender 的 `on_init` 真正触发
   (data channel 建好)才去订阅本地 topic**,反过来做的话消息可能在
   `m_data_channel_id` 还没赋值时就到达。`from_corelink` 方向反而是先建好本地
   publisher 更保险(不需要等谁,而且 receiver 的 `on_receive` 有可能先于
   `on_init` 触发)。

5. **线程模型**:Corelink 的所有回调(`on_receive`/`on_init`/`on_error`/
   `request()` 的 completion handler)都跑在 Corelink 自己内部的事件循环线程上
   (`init_protocols()` 时起的,asio/libwebsockets 那条线),不是 ROS2 executor
   线程。`rclcpp` 的 `publish()` 从任意线程调用是安全的(不碰 executor/waitset),
   所以现在直接在 Corelink 回调里调用 `publish()`,没有额外做线程安全队列。
   如果之后观察到这样会卡 Corelink 的事件循环,再加队列。

## `corelink_cpp/` 里打的 3 个编译补丁(细节看 `CORELINK_PATCHES.md`)

这台机器(Ubuntu 22.04 + GCC 11.4 + apt 装的 asio/rapidjson/libwebsockets/openssl)
上编译 `corelink_cpp/` 时踩到 3 个 corelink 库自身的 bug,已经修好:

1. `corelink_network_constants.hpp` 缺 `#include <cstring>`(`std::strcmp` 编不过)
2. `corelink_data_xchg_websocket_proto_manager.cc` 用了 libwebsockets 4.0.20 里
   不存在的 `connect_timeout_secs` 字段(apt 装的版本太老),用宏守卫掉了
3. `corelink_client_connection_info.hpp` 里几个静态成员定义在头文件里没加
   `inline`,导致多个 .cpp 文件都 include 它时链接报"重复定义"(ODR 违规)

**换电脑重写时大概率会重新踩到这三个坑**(除非依赖版本刚好不一样),
直接照抄这三处修法就行,不用重新调试一遍。

## 编译依赖

`corelink_all.hpp` 这个总头文件(`corelink_cpp/include/corelink_all.hpp`)决定了到底
需要哪些第三方库——它 include 了 `asio_includes.hpp` / `json_includes.hpp`,
再加上 `.cc` 文件里直接用到的 `libwebsockets.h`,一共 4 个第三方依赖,外加
编译器/ROS2 本身:

| 依赖 | 这台机器上的版本 | 装哪来的 | 为什么需要 |
|---|---|---|---|
| **asio(standalone 版,不是 boost::asio)** | 1:1.18.1-1 | `apt install libasio-dev` | `commons/asio_includes.hpp` 直接 `#include "asio.hpp"`,corelink 的异步网络 IO(control channel 的 event loop)靠它 |
| **RapidJSON** | 1.1.0+dfsg2-7 | `apt install rapidjson-dev` | `commons/json_includes.hpp` 用它做 `corelink::utils::json` 的底层实现,所有 request/response 的 JSON 编解码都靠它 |
| **libwebsockets** | 4.0.20-2ubuntu1.1 | `apt install libwebsockets-dev` | control channel 默认走的 `wss://` 协议实现,`corelink_data_xchg_websocket_proto_manager.*` 直接调它的 C API |
| **OpenSSL**(libssl + libcrypto) | 3.0.2 | `apt install libssl-dev` | 给 libwebsockets 的 TLS 用,corelink 自己代码没有直接调 OpenSSL API |
| **CMake** | 3.22.1(`corelink_cpp/CMakeLists.txt` 要求 ≥3.20) | 系统自带/apt | 构建系统 |
| **GCC/g++** | 11.4.0 | 系统自带 | 编译器,注意上面那 3 个补丁就是在这个版本上踩到的坑,换编译器版本可能坑不一样 |
| **ROS2 Humble(`rclcpp` 16.0.19)** | — | `/opt/ros/humble`,系统装好的 | `ros2_bridge_node` 自己这层要用,`GenericSubscription`/`GenericPublisher` 都来自这里;corelink 库本身不需要 ROS2 |

一条命令装齐 4 个第三方依赖:

```bash
sudo apt install -y libasio-dev rapidjson-dev libwebsockets-dev libssl-dev
```

`CMakeLists.txt` 里那几个 `CORELINK_ASIO_CPP_PATH` / `CORELINK_RAPID_JSON_CPP_PATH` /
`CORELINK_LWS_INCLUDE_PATH` / `CORELINK_OPENSSL_INCLUDE_PATH` / `CORELINK_LWS_LIB_PATH` /
`CORELINK_OPENSSL_LIB_PATH` 这些 cache 变量,默认值都写死成 `/usr/include`、
`/usr/lib/x86_64-linux-gnu`——这是上面这几个 apt 包在 Ubuntu/Debian 上装的标准位置。
换电脑如果发行版不一样、或者路径不一样,改这几个变量就行,不用改 `corelink_cpp/` 本身。

## 编译方法(在这台机器上验证过,完整跑通)

```bash
sudo apt install -y libasio-dev rapidjson-dev libwebsockets-dev libssl-dev
source /opt/ros/humble/setup.bash
cd bridge_node
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build . -j$(nproc)
```

编译产物:`bridge_node/build/ros2_bridge_node`(可执行文件),
以及 `bridge_node/build/corelink_cpp_build/libcorelinkclient.so`。

编辑器 IntelliSense 报 `rclcpp` 找不到的话,是 VSCode CMake Tools 插件的
`cmake.sourceDirectory` 配置问题——现在仓库是单一 CMake 项目(根目录一份
`CMakeLists.txt`,`add_subdirectory(corelink_cpp)` 把 corelink 库编进来),
`cmake.sourceDirectory` 指向仓库根目录即可,不需要再配多个路径。

## 2026-07-15 调试记录:修了 6 个 bug,连接确认可用,端到端投递还没打通

这次是第一次真的拿这份代码去连真实 Corelink 服务器(`corelink.hsrn.nyu.edu`),
之前从没跑到这一步(`bridge_node.cpp` 的最新改动之前也没编译验证过)。过程中
发现并修了 6 个真实 bug:

1. `bridge_node.cpp` 顶部一段没删干净的 zstd 实验代码(`#include "zstd_common.h"`,
   这个头文件系统里根本不存在)——不删连编译都过不了
2. `topic.direction` 参数值对不上:代码原来校验的是 `to_corelink_server`/
   `from_corelink_server`,但 `config/*.yaml` 写的是 `to_corelink`/`from_corelink`
   ——已经把代码改成跟 yaml 一致(`to_corelink`/`from_corelink`),不是改 yaml
3. `qos` 参数没有 `declare_parameter` 就直接 `get_parameter("qos").as_int()`,
   而且 yaml 里原来写的是带引号的字符串 `"10"`——补了 `declare_parameter<int>`,
   yaml 也改成不带引号的 `10`
4. `setupToCorelink()` 里 `createSender` 的回调 lambda 只捕获了 `[this]`,但函数体里用了外层局部变量
   `qos`——编译器(clangd)直接报错,改成 `[this, qos]`
5. **`CorelinkTransport` 构造函数原来按值传 `protocol` 参数,但 corelink 库的
   `corelink_client_connection_info::protocol` 成员其实是 `const protocol&`
   引用(不是拷贝!)。**按值传参会在 `CorelinkTransport` 构造函数返回的瞬间
   产生悬垂引用,后面 `connect()` 里读到的是垃圾值,表现为一个具有迷惑性的
   报错:`"Could not locate a proto manager for supplied control channel
   protocol"`,一度以为是 corelink 库本身的 bug(还专门编译官方
   `basic-connect-test.cpp` 例子对比排查,例子能正常连上,才确认是我们自己代码
   的问题)。修法:`corelink_transport.hpp`/`.cpp` 里 `control_protocol` 参数改成
   `const protocol&`
6. **同样的悬垂引用问题在 `createSender`/`createReceiver`(`data_protocol` 参数)
   以及 `bridge_node.cpp` 的 `protocolFromString()` 里各自又出现一次**——这几个函数
   内部经过 `modify_sender_stream_request`/`modify_receiver_stream_request` 时又会
   碰到 corelink 库另一个同款引用成员(`modify_data_stream_request_base::protocol`
   同样是 `const protocol&`)。这一层不修的话,认证能过、但一创建 sender/receiver
   流就直接 segfault。修法:`createSender`/`createReceiver` 的 `data_protocol` 参数、
   `protocolFromString()` 的返回值,全部改成返回/传递 `const protocol&`,并且调用处
   (`setupToCorelink`/`setupFromCorelink`)对应的 `const auto data_protocol = ...`
   也要改成 `const auto &data_protocol = ...`,否则又会在绑定处产生一次拷贝把引用链
   斩断。

**结论:corelink 库里凡是存 `core::network::constants::protocols::protocol` 的地方
(`corelink_client_connection_info::protocol`、`modify_data_stream_request_base::protocol`
等),存的都是引用,不是拷贝。**这是一个编译器完全不会报错、只在运行时表现为
诡异行为(认证失败 / segfault)的坑,以后往 `CorelinkTransport` 或直接用 corelink
库时新增代码,传 `protocol` 类型的参数**一律用 `const protocol&`,不要按值传**,
并且要保证引用链最终指向 `protocols::tcp`/`udp`/`websocket` 这几个 `static constexpr`
全局对象,中途任何一环变成局部拷贝都会导致悬垂引用。

修完这 6 个之后,**确认可用**:连接真实服务器 → 认证 → 创建 sender/receiver 数据流
→ 往 Corelink 发数据,UDP 和 websocket 协议都测过,连续发几十条消息不崩溃、不报错。

**还没确认可用**:实际的消息投递(sender 发出去之后,receiver 端 `on_receive`
真的触发)。在同一台机器上用两个不同 `ROS_DOMAIN_ID`(隔离本地 DDS,逼消息必须真的
走 Corelink 才能到)测试了好几轮——UDP vs websocket 协议都试过、`corelink.workspace`
占位值 `robot1` 和服务器上确认真实存在的 `Chalktalk`(用官方 `ex_get_workspaces()`
例子拉取过真实列表确认过)都试过——receiver 端的 `on_receive` 始终没有被触发过一次。
往 `corelink_client.hpp` 的 `handle_create_receiver`/`server_callback_on_subscribed`
等处又翻了一层也没能定位到明确原因,判断这已经超出"读代码能确定"的范围了。

（为了方便下次继续排查,`onLocalMessage`/`onCorelinkMessage` 里各留了一行
`RCLCPP_INFO` 调试日志,故意保留,不是遗漏。）

## 还没做 / 待确认的事(接下来继续要做的)

- [ ] **消息投递没打通(新发现的问题,优先级最高)**:sender/receiver 流都能建立成功,
      但消息从来没有真的从 receiver 端收到过。已经排除了协议(UDP/websocket 都试过)
      和 workspace(占位值/真实值都试过)这两个变量。下一步要么直接问 Corelink 团队
      "两个 create_sender/create_receiver 建在同一个 workspace/stream_type 下,
      receiver 为什么收不到 sender 发的数据",要么换两台真正独立的机器(不是同机
      跑两个进程)重测一遍,排除是不是同机测试触发了什么边界情况
- [ ] **确认 Corelink workspace**:`config/*.yaml` 里 `corelink.workspace: "robot1"`
      是占位值,而且已经确认它**不在**服务器当前的真实 workspace 列表里(拉取到的
      列表是 `Log`/`Holodeck`/`Chalktalk`/`Infinite`/`wsexample`/`metaroom`/
      `Hello World`/`Hello NYU`/`Workspace1`/`Workspace2`/几个 `verizon_*`/
      `shubham_ws`)。得先跟 Corelink 团队确认这个项目实际分到的 workspace 名字
      (workspace 需要服务器端预先 provision 好才能用)——注意换成 `Chalktalk`
      之后消息投递依然没打通,所以 workspace 不对大概率不是(唯一)根因
- [ ] **换掉默认账号密码**:现在用的是 `corelink_client_connection_info` 自带的
      默认测试账号(`Testuser`/`Testpassword`)
- [ ] 没做重连逻辑(`on_connection_uninit` 触发后,当前代码不会自动重建
      sender/receiver stream)——先跑通happy path,这个留到后面
- [ ] 没验证 `send_data()` 在多线程并发调用下是否线程安全(如果以后用
      `MultiThreadedExecutor` 桥多个 topic 会需要确认)
- [ ] 还是单 topic 单方向的最小版本,没做 config 驱动的多 topic
      `TopicBridgeManager` + YAML 多条目支持

## 建议在新电脑上重写时的顺序

跟当初设计时想的顺序一样,建议照做,不要一上来就写全:
1. 先把 `CorelinkTransport` 写出来,单独写个 `main.cpp` 手动调用它
   connect→createSender→sendData,不接 ROS2,确认 Corelink 这一层本身通不通
2. 再写 `BridgeNode`,先只支持 `to_corelink` 一个方向,硬编码一个 topic 跑通
3. 加 `from_corelink` 方向
4. 参数化(declare_parameter),配上 yaml
5. 需要的话再泛化成多 topic

这个顺序比照着现成代码抄一遍更容易真正理解每一步"为什么这么写"。


谁拥有 buffer？
buffer 活多久？
ROS 能不能直接接管 Corelink buffer？
Corelink 能不能直接接管 ROS SerializedMessage buffer？
allocator 是否兼容？
发送是同步还是异步？

/image_raw
    ↓ image compression node
/image/compressed
    ↓
Bridge
    ↓
Corelink

ROS CompressedImage
        ↓
CDR serialization
        ↓
Corelink


sensor_msgs/Image CDR
        ↓ deserialize
sensor_msgs::msg::Image
        ↓ JPEG/H264 encode
compressed bytes
        ↓ Corelink


你的论文 benchmark 最好同时记录
1. ROS input payload bandwidth
   ros2 topic bw

2. Bridge application payload bandwidth
   sum(serialized message bytes)

3. Actual network interface bytes
   NIC TX/RX counters

4. Message rate
   messages/s

5. CPU usage

6. End-to-end latency

7. packet loss / message loss



zstd compression

lossless -> no impact
loss -> possible

depth -> geometry error

base64「方案选单」 
3 bytes -> 4 text characters

corelink小包