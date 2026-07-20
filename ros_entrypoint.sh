#!/bin/bash
set -e

# source ROS2
source /opt/ros/humble/setup.bash

# source
if [ -f "${ROS_WS}/install/setup.bash" ]; then
    source "${ROS_WS}/install/setup.bash"
fi

exec "$@"
