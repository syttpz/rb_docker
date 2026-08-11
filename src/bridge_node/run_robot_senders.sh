#!/usr/bin/env bash
# ROBOT side, RGB-D: push color + aligned depth + camera_info INTO corelink,
# i.e. the three streams rtabmap_offload/offload.launch.py receives.
#
# This is the plain-cmake counterpart of robot_senders.launch.py -- use the
# launch file if the workspace is colcon-built, this script if you only ran
# build.sh (which produces ./build/ros2_bridge_node and installs nothing).
#
#   ./run_robot_senders.sh              # build + run
#   ./run_robot_senders.sh --no-build   # skip the build step
#   RATE=0.2 ./run_robot_senders.sh     # also replay a bag at that rate
#   BAG=../../datasets/fr1_desk_rs RATE=0.2 ./run_robot_senders.sh
#
# Pacing defaults assume ~6 Hz on the wire (a 30 Hz bag played at --rate 0.2):
# 921,600 B of RGB is ~57 fragments at 16 KB, so (166667 us / 57) / 2 ~ 1400;
# 614,400 B of depth is ~38 fragments -> ~2100. Raise the rate and these have
# to come down proportionally or the pacer queue overflows.
set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" != "--no-build" && "${SKIP_BUILD:-0}" != "1" ]]; then
  "$HERE/build.sh"
fi

source /opt/ros/humble/setup.bash
set -u

BIN="$HERE/build/ros2_bridge_node"
PARAMS="$HERE/config/robot_side.yaml"
CREDS="$HERE/config/credentials.yaml"

PROTO="${PROTO:-udp}"
REL="${REL:-best_effort}"
QUEUE_MAX="${QUEUE_MAX:-256}"
RGB_PACING="${RGB_PACING:-1400}"
DEPTH_PACING="${DEPTH_PACING:-2100}"
INFO_PACING="${INFO_PACING:-0}"

[[ -x "$BIN" ]] || { echo "missing $BIN -- run build.sh" >&2; exit 1; }
[[ -f "$CREDS" ]] || { echo "missing $CREDS -- copy credentials.yaml.example" >&2; exit 1; }

pids=()
# Kill the whole group on exit so one dead sender never leaves the rest
# half-streaming into the shared Corelink server.
cleanup() {
  trap - EXIT INT TERM
  [[ ${#pids[@]} -gt 0 ]] && kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sender() {
  local name="$1" topic="$2" type="$3" pacing="$4"
  echo "[robot] $name: $topic ($type) --$PROTO--> corelink  pacing=${pacing}us"
  "$BIN" --ros-args \
      -r __node:="$name" \
      --params-file "$PARAMS" \
      --params-file "$CREDS" \
      -p topic.name:="$topic" \
      -p topic.type:="$type" \
      -p topic.direction:=to_corelink \
      -p qos.reliability:="$REL" \
      -p corelink.data_protocol:="$PROTO" \
      -p send.pacing_us:="$pacing" \
      -p send.pacing_queue_max:="$QUEUE_MAX" &
  pids+=($!)
}

sender color_image_sender \
    /camera/camera/color/image_raw                   sensor_msgs/msg/Image      "$RGB_PACING"
sender depth_image_sender \
    /camera/camera/aligned_depth_to_color/image_raw  sensor_msgs/msg/Image      "$DEPTH_PACING"
sender camera_info_sender \
    /camera/camera/color/camera_info                 sensor_msgs/msg/CameraInfo "$INFO_PACING"

if [[ -n "${BAG:-}" ]]; then
  # Give the senders time to authenticate and open their streams before the
  # first frame arrives, otherwise the head of the bag is dropped.
  echo "[robot] waiting 8s for corelink streams, then playing $BAG at ${RATE:-1.0}x"
  sleep 8
  ros2 bag play "$BAG" --rate "${RATE:-1.0}"
  echo "[robot] bag finished; senders still up (ctrl-c to stop)"
fi

# Exit as soon as ANY sender dies, rather than sitting on a partial stream.
wait -n
echo "[robot] a sender exited -- shutting the rest down" >&2
