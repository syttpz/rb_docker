# Build & Run

## 1. 装依赖

```bash
sudo apt install -y libasio-dev rapidjson-dev libwebsockets-dev libssl-dev
```

还需要系统装好 ROS2 Humble(`/opt/ros/humble`)。Corelink C++ 客户端(`corelink_cpp/`)
已经作为带补丁的快照 vendor 在仓库里,不用单独装。

## 2. Build

```bash
source /opt/ros/humble/setup.bash
cd bridge_node
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build . -j$(nproc)
```

产物:`bridge_node/build/ros2_bridge_node`(可执行文件)。

改动过代码之后,重新 build 只用重跑最后一行 `cmake --build . -j$(nproc)`,
不用重新 `cmake ..`(除非改了 `CMakeLists.txt` 或加/删了源文件)。

## 3. Run

可执行文件是普通 rclcpp 程序,不经过 colcon/`ros2 launch`,直接用
`--ros-args --params-file` 加载 `config/` 下的 yaml:

```bash
source /opt/ros/humble/setup.bash
cd bridge_node/build
./ros2_bridge_node --ros-args --params-file ../config/robot_side.yaml
```

### 本机双进程联调(需要真实 Corelink 服务器可达)

`robot_side.yaml`(`to_corelink`)和 `server_side.yaml`(`from_corelink`)是配对的
一对:一个把本地 `/chatter` 转发进 Corelink,另一个从 Corelink 收回来再发布成
本地 `/chatter`。同一台机器上跑两个进程测试时,要用不同 `ROS_DOMAIN_ID` 把两边
的本地 DDS 隔开,否则 `/chatter` 会直接被本地 DDS 发现机制打通,分不清消息到底是
不是真的走了 Corelink:

```bash
# 终端 1 —— 模拟机器人这一侧
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=1
cd bridge_node/build
./ros2_bridge_node --ros-args --params-file ../config/robot_side.yaml

# 终端 2 —— 模拟服务器这一侧
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=2
cd bridge_node/build
./ros2_bridge_node --ros-args --params-file ../config/server_side.yaml

# 终端 3 —— 在机器人域里发消息、在服务器域里确认收到
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=1
ros2 topic pub /chatter std_msgs/msg/String "{data: 'hello'}"

# 另开一个终端,ROS_DOMAIN_ID=2,应该能看到 /chatter 有消息(如果桥接打通了)
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=2
ros2 topic echo /chatter
```

### 单个参数覆盖,不改 yaml

```bash
./ros2_bridge_node --ros-args --params-file ../config/robot_side.yaml \
  -p corelink.workspace:=Chalktalk
```

## 现状提醒

截至最近一次调试(见 `HANDOFF.md`),连接/认证/建流已确认可用,但
**receiver 端消息投递还没打通**——按上面步骤跑通到"终端 3 发消息"是预期的,
但终端 4 的 `ros2 topic echo` 大概率还收不到,这是已知的待排查问题,不是操作错误。
默认账号密码(`Testuser`/`Testpassword`)和占位 workspace(`robot1`)也都还没换成
真实值,细节和完整 TODO 列表见 `HANDOFF.md`。
