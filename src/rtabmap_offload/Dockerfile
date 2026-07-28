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



RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rtabmap-ros \
        ros-humble-navigation2 \
        ros-humble-nav2-bringup \
    && rm -rf /var/lib/apt/lists/*


RUN apt-get update && apt-get install -y --no-install-recommends \
        libasio-dev \
        rapidjson-dev \
        libwebsockets-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*


ENV ROS_WS=/ros_ws

RUN mkdir -p ${ROS_WS}/src

WORKDIR ${ROS_WS}/src

RUN git clone --branch fragment --single-branch \
    https://github.com/syttpz/rb_docker.git

WORKDIR ${ROS_WS}

RUN source /opt/ros/humble/setup.bash && \
    colcon build \
        --symlink-install \
        --cmake-args -DCMAKE_BUILD_TYPE=Release



RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc && \
    echo "[ -f ${ROS_WS}/install/setup.bash ] && source ${ROS_WS}/install/setup.bash" >> /root/.bashrc



RUN chmod +x ${ROS_WS}/src/rb_docker/ros_entrypoint.sh

ENTRYPOINT ["/ros_ws/src/rb_docker/ros_entrypoint.sh"]


CMD ["ros2", "run", "ros2_bridge_node", "ros2_bridge_node", \
     "--ros-args", \
     "--params-file", "/ros_ws/install/ros2_bridge_node/share/ros2_bridge_node/config/server_side.yaml", \
     "-p", "topic.name:=/battery_state", \
     "-p", "topic.type:=sensor_msgs/msg/BatteryState", \
     "-p", "qos.reliability:=best_effort", \
     "-p", "corelink.data_protocol:=udp"]