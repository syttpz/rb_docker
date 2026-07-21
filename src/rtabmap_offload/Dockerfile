#  build on an amd64 server (this is the offload/compute side, not the
#  robot's arm64 Pi -- --platform is pinned below so this always builds
#  amd64 even if run on an arm64 dev machine by mistake):
#
#     docker build --platform linux/amd64 -f src/rtabmap_offload/Dockerfile -t rtabmap_offload:humble ./src
#
#  (build context is ./src, not repo root, so this Dockerfile can COPY in
#  its sibling bridge_node/ package -- see below)
#
#  run: this image also runs a ros2_bridge_node instance (direction:
#  from_corelink, see bridge_node/config/server_side.yaml) to receive
#  whatever the robot forwards over Corelink and republish it into this
#  container's local ROS2 graph for rtabmap to consume. config/credentials.yaml
#  is gitignored and never baked into the image -- mount the real one at
#  runtime:
#
#     docker run -it --rm \
#        --network host \
#        -v $(pwd)/src/bridge_node/config:/root/ros2_ws/src/bridge_node/config \
#        rtabmap_offload:humble
#
#  Nothing here launches rtabmap or the bridge automatically (CMD is a
#  plain shell) -- start them by hand once inside, same two-piece pattern
#  as bridge_node/BUILD.md's manual dual-process walkthrough:
#     source /opt/ros/humble/setup.bash
#     cd /root/ros2_ws/src/bridge_node/build
#     ./ros2_bridge_node --ros-args --params-file ../config/server_side.yaml \
#       --params-file ../config/credentials.yaml -p corelink.data_protocol:=tcp &
#     ros2 launch rtabmap_launch rtabmap.launch.py \
#       rgb_topic:=/camera/camera/color/image_raw/compressed  # remap to whatever bridge_node republished locally

FROM --platform=linux/amd64 ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.utf8

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        vim \
        ca-certificates \
        build-essential \
        cmake \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# rtabmap itself -- this image exists to run this. ros-humble-rtabmap-ros
# pulls in its own SLAM/point-cloud dependency chain (PCL, octomap, etc.)
# via apt. image-transport-plugins decodes whatever compressed image
# transport the robot side is bridging (see bridge_node's RealSense
# benchmark notes on why raw/uncompressed doesn't survive the Corelink
# UDP hop -- this offload side needs to decompress what actually arrives).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rtabmap-ros \
        ros-humble-image-transport-plugins \
        ros-humble-robot-localization \
        ros-humble-tf2-tools \
    && rm -rf /var/lib/apt/lists/*

# corelink build dependencies, matching the root Dockerfile and
# bridge_node/CORELINK_PATCHES.md -- this is what corelink_cpp (vendored
# in bridge_node/corelink_cpp/) compiles against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasio-dev \
        rapidjson-dev \
        libwebsockets-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

ENV ROS_WS=/root/ros2_ws
RUN mkdir -p ${ROS_WS}/src
WORKDIR ${ROS_WS}

# bridge_node isn't colcon-integrated (deliberately, see
# bridge_node/HANDOFF.md) -- built directly with cmake, same steps as
# bridge_node/BUILD.md documents for a dev machine.
COPY bridge_node ${ROS_WS}/src/bridge_node
RUN source /opt/ros/humble/setup.bash && \
    cd ${ROS_WS}/src/bridge_node && \
    mkdir -p build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    cmake --build . -j$(nproc)

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc

CMD ["bash"]
