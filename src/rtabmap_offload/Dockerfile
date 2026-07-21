# build on k8s  
#   docker build -t robot:humble .

FROM --platform=linux/amd64 ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.utf8

SHELL ["/bin/bash", "-c"]

# essential dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        wget \
        vim \
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

# RTAB-Map 
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Rtabmap
        ros-humble-rtabmap-ros \
        # Nav2
        ros2-humble-navigation2 \
        ros2-humble-nav2-bringup \
    && rm -rf /var/lib/apt/lists/*

# corelink build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasio-dev \
        rapidjson-dev \
        libwebsockets-dev \
    && rm -rf /var/lib/apt/lists/*

# workspacebridge_nodebridge_node
ENV ROS_WS=/ros_ws
RUN mkdir -p ${ROS_WS}/src
WORKDIR ${ROS_WS}

# Auto source
RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc && \
    echo "[ -f ${ROS_WS}/install/setup.bash ] && source ${ROS_WS}/install/setup.bash" >> /root/.bashrc

# clone bridge_node
RUN git clone git@github.com:syttpz/rb_docker.git

WORKDIR ${ROS_WS}/src/rb_docker/src/bridge_node

# build
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*
RUN colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release


CMD ["/bin/bash"]
