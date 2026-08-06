#!/usr/bin/env bash
# SERVER side: pull the compressed image FROM corelink and republish it as a
# local ROS2 topic (topic.direction=from_corelink). Builds first unless --no-build.
#
#   ./run_server.sh                # build + run, receive compressed image over UDP
#   ./run_server.sh --no-build     # skip the build step
#   PROTO=tcp ./run_server.sh      # must match the robot side's transport
#   TOPIC=/foo TYPE=std_msgs/msg/String ./run_server.sh   # bridge a different topic
#

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" != "--no-build" && "${SKIP_BUILD:-0}" != "1" ]]; then
  "$HERE/build.sh"
fi

# Source ROS before `set -u`: its setup scripts reference unbound vars.
source /opt/ros/humble/setup.bash
set -u

TOPIC="${TOPIC:-/camera/camera/color/image_raw/compressed}"
TYPE="${TYPE:-sensor_msgs/msg/CompressedImage}"
PROTO="${PROTO:-udp}"
REL="${REL:-best_effort}"

echo "[server] corelink --$PROTO--> republish $TOPIC ($TYPE)  [qos.reliability=$REL]"
exec "$HERE/build/ros2_bridge_node" --ros-args \
    --params-file "$HERE/config/server_side.yaml" \
    --params-file "$HERE/config/credentials.yaml" \
    -p topic.name:="$TOPIC" \
    -p topic.type:="$TYPE" \
    -p topic.direction:=from_corelink \
    -p qos.reliability:="$REL" \
    -p corelink.data_protocol:="$PROTO"
