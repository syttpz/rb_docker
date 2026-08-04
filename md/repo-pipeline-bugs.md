# Repository, deployment and script issues

## RP-01：rosbag 的 compressed topic 拼写错误

- 严重度：P0（数据采集）
- 证据：代码确认
- 位置：`src/startmapping.sh:107-108`

脚本写的是：

```bash
"$CAM_NS/color/image_raw\compressed"
"$CAM_NS/color/image_raw\compressedDepth"
```

双引号中的反斜杠在这里不会变成 `/`，最终 topic 名含反斜杠，与 ROS RealSense 的 `/compressed` 和 `/compressedDepth` 不同。脚本可能看似正常运行，但 bag 中缺少预期压缩 topic。

## RP-02：offload Dockerfile 构建的不是当前分支

- 严重度：P1
- 证据：代码确认
- 位置：`src/rtabmap_offload/Dockerfile:48`

Dockerfile 固定 clone GitHub 的 `fragment` 分支，而当前开发分支是 `zstd`。镜像内容取决于远端分支状态，不是本地 checkout，也不会包含本地未 push 的修改。

这会造成“以为在测试修复版，实际容器仍是旧版”的实验污染。


## RP-04：offload 默认命令没有运行 RTAB-Map

- 严重度：P1
- 证据：代码确认

镜像默认只运行 bridge receiver，并且 topic 是 `/battery_state`。Kubernetes deployment 也没有覆盖 command。因此当前 deployment 名为 `rtabmap-offload`，实际不会建图。

## RP-05：Kubernetes 暴露不存在的 HTTP 端口

- 严重度：P2
- 证据：代码确认

deployment 声明 container port 8080，但仓库中没有 HTTP server。端口声明本身不会启动服务，容易误导 service/health-check 配置。

## RP-06：顶层 ARM64 镜像与 CMake 的 x86_64 默认库路径冲突

- 严重度：P1
- 证据：高风险潜在问题
- 位置：根 `Dockerfile` 与 `src/bridge_node/CMakeLists.txt`

根镜像指定 `linux/arm64`，CMake cache defaults 却指向 `/usr/lib/x86_64-linux-gnu`。若 vendored Corelink CMake 实际使用这些路径链接 OpenSSL/libwebsockets，Pi 构建会失败或找不到库。

需要分别在目标 ARM64 和 amd64 镜像执行干净 `colcon build` 确认。

## RP-07：Zstd 源码未接入且当前不可编译

- 严重度：P1（如果当前分支目标是压缩）
- 证据：代码确认
- 位置：`compression.cpp/.hpp` 与 bridge CMake

现状：

- `compression.cpp` 没有加入任何 target；
- bridge 没有调用压缩/解压；
- 声明与定义参数不同；
- 使用未定义的 `fname`、`fin`、`fout`；
- `auto` 函数参数需要 C++20，而工程设置 C++17；
- executable 风格的 `main()` 与 bridge node 集成方式尚未确定；
- package/CMake 没有声明或链接 zstd。

因此分支名虽为 `zstd`，实际传输仍是未压缩 CDR + 分片。

## RP-08：credentials 文件已被 Git 跟踪

- 严重度：P1（安全/配置）
- 证据：代码确认

`src/bridge_node/config/credentials.yaml` 已在 Git index 中，即使 `.gitignore` 后来忽略它也不会停止跟踪。README 所说“gitignored、镜像里不会有”不成立。

需要先判断当前值是不是可用凭据；如果是，应轮换，并考虑历史清理。此文档不复制凭据内容。

## RP-09：多个 Markdown 引用了不存在的文档

- 严重度：P2
- 证据：代码确认

缺失引用包括：

- `HANDOFF.md`
- `BUILD.md`
- `CORELINK_PATCHES.md`
- RTAB-Map README 中路径错误的 benchmark 文档

vendored Corelink README 也指向未纳入仓库的 `docs/` 目录。

## RP-10：benchmark 文档描述的是分片实现之前的行为

- 严重度：P1（实验解释）
- 证据：代码确认

文档仍说 raw CDR 会整帧送入 Corelink、超过 20,000 字节必然失败；当前 bridge 已经统一切成 19,000 字节 payload。旧 benchmark 对历史版本有效，不能描述当前分支。

报告应记录 commit hash，否则同名场景的结论会互相矛盾。

## RP-11：`rtabmap_offload/src/node.launch.py` 指向不存在的 ROS package/executable

- 严重度：P2
- 证据：代码确认

launch 文件创建 `package='rtabmap_offload'`、`executable='rtabmap_offload_node'`，但该目录没有对应 `package.xml`、构建文件或 node 实现。它目前是不可运行的占位文件。

## RP-12：顶层 compose 的 `robot` 容器不会自动构建 workspace

- 严重度：P2
- 证据：代码确认

`./src` 被挂到 `/root/ros2_ws/src`，但镜像 build 阶段没有复制或 colcon build 这些源码；默认 command 又是 `bash`。除非镜像 tag 已预装产物或用户手动 build，`ros2 run ros2_bridge_node ...` 不一定存在。

## RP-13：固定默认测试账号和 workspace 会造成误连接风险

- 严重度：P2
- 证据：代码确认

代码和 YAML 有非空默认 endpoint、username/password、workspace。忘记加载 credentials/params 时，节点不会因缺配置失败，而可能连接公共测试空间。实验之间也可能因为相同 stream type 互相订阅。
