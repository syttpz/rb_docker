# rtabmap_offload

给"服务器/离线算力"这一侧用的镜像,跟根目录那个 `Dockerfile`(机器人 Pi,
arm64,带 RealSense 驱动)是分开的两回事——这边是纯 amd64,不装相机驱动,
只装 rtabmap 本身 + `bridge_node`(用来从 Corelink 收机器人转发过来的数据,
细节见 `../bridge_node/HANDOFF.md`)。

这个目录目前只有一个 Dockerfile,**没有接进 `docker-compose.yml`**,启动流程
还是手动的两步(bridge_node 收流 + rtabmap 处理),原因是目前还没有验证过
真实的 rtabmap 输入 topic 该接哪个(`/battery_state`/`/chatter` 这两个测过的
topic 都跟建图无关,实际要接的应该是相机数据,而 `REALSENSE_UDP_BENCHMARK.md`
里已经验证过原始 `image_raw` 走 UDP 会因为 corelink 的 20000 字节 channel MTU
限制 100% 失败——真正对接 rtabmap 之前,这个"该转发哪个 topic、用什么协议"
的问题得先定下来,不然装进 compose 里也跑不通)。

## Build

```bash
# 在仓库根目录下
docker build --platform linux/amd64 -f src/rtabmap_offload/Dockerfile -t rtabmap_offload:humble ./src
```

注意 build context 是 `./src` 不是仓库根目录——这样 Dockerfile 才能直接
`COPY bridge_node ...` 把旁边这个包一起打进镜像(`bridge_node` 不走 colcon,
直接 cmake 编译,见 `../bridge_node/BUILD.md`)。

## Run

`bridge_node/config/credentials.yaml` 是 gitignore 掉的,镜像里不会有,跑的时候
挂载真实的 config 目录进去(跟根目录那个 `docker-compose.yml` 里机器人那侧
用 volume 挂 `./src` 是同样的道理,这边范围小一点,只挂 config):

```bash
docker run -it --rm \
  --network host \
  -v $(pwd)/src/bridge_node/config:/root/ros2_ws/src/bridge_node/config \
  rtabmap_offload:humble
```

进容器之后手动起两个东西(镜像本身不自动跑任何东西,`CMD` 就是纯 `bash`):

```bash
# 1. bridge_node,收 corelink 转发过来的数据,发布成本地 ROS2 topic
source /opt/ros/humble/setup.bash
cd /root/ros2_ws/src/bridge_node/build
./ros2_bridge_node --ros-args \
  --params-file ../config/server_side.yaml \
  --params-file ../config/credentials.yaml \
  -p corelink.data_protocol:=tcp &

# 2. rtabmap,消费上面发布出来的本地 topic(topic 名字/协议还没最终定,
#    这里只是占位,实际要按 (1) 里 bridge_node 真正在转发的 topic 改)
ros2 launch rtabmap_launch rtabmap.launch.py \
  rgb_topic:=/camera/camera/color/image_raw/compressed
```
