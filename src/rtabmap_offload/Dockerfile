# Server-side offload image: Corelink receivers + RTAB-Map.
#
# Build from the REPO ROOT so the local working tree is what ends up in the
# image (this replaced a `git clone --branch fragment`, which meant the image
# never contained the code you were actually editing):
#
#   docker build -f src/rtabmap_offload/Dockerfile -t eddyhu217/offload:<tag> .
#
FROM --platform=linux/amd64 ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.utf8

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        wget \
        vim \
        git \
        gnupg2 \
        lsb-release \
        ca-certificates \
        software-properties-common \
        udev \
        usbutils \
        python3-pip \
        build-essential \
        cmake \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# rtabmap_ros in humble is split: rtabmap_sync (rgbd_sync),
# rtabmap_odom (rgbd_odometry), rtabmap_slam (rtabmap).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rtabmap-ros \
        ros-humble-compressed-image-transport \
        ros-humble-compressed-depth-image-transport \
        ros-humble-navigation2 \
        ros-humble-nav2-bringup \
    && rm -rf /var/lib/apt/lists/*

# corelink_cpp build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasio-dev \
        rapidjson-dev \
        libwebsockets-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

ENV ROS_WS=/ros_ws

# Only the two ROS packages -- see .dockerignore for what is kept out of the
# build context (datasets/, src/maps/, build artefacts).
COPY src/bridge_node ${ROS_WS}/src/bridge_node
COPY src/rtabmap_offload ${ROS_WS}/src/rtabmap_offload
COPY ros_entrypoint.sh /ros_entrypoint.sh

WORKDIR ${ROS_WS}

RUN source /opt/ros/humble/setup.bash && \
    colcon build \
        --symlink-install \
        --cmake-args -DCMAKE_BUILD_TYPE=Release

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc && \
    echo "[ -f ${ROS_WS}/install/setup.bash ] && source ${ROS_WS}/install/setup.bash" >> /root/.bashrc

RUN chmod +x /ros_entrypoint.sh

# Recorded so a running pod can be traced back to a commit, per the
# reproducibility requirements in md/thesis-research-plan.md.
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_DATE=${BUILD_DATE}
LABEL org.opencontainers.image.revision="${GIT_COMMIT}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"

ENTRYPOINT ["/ros_entrypoint.sh"]

# Receivers + rgbd_sync + rgbd_odometry + rtabmap. The old CMD started four
# bare bridge nodes and no mapping at all; one of them re-sent
# /camera/camera/color/camera_info back to the same Corelink stream a receiver
# was subscribed to, which is a feedback loop.
CMD ["ros2", "launch", "rtabmap_offload", "offload.launch.py"]
