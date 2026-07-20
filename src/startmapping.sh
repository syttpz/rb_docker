#!/usr/bin/env bash
#
# startmapping.sh — RGBD SLAM (rtabmap) for the Create 3 + Intel RealSense.
#
# The Create 3 has NO lidar, so we map from the RealSense depth+color camera
# plus the robot's wheel /odom. rtabmap builds a 2D occupancy grid (/map) and
# a 3D database.
#
# ON Ctrl-C this script saves, into  src/maps/  (bind-mounted to the Pi):
#     my_map.pgm / my_map.yaml   <- 2D occupancy grid
#     rtabmap.db                 <- full 3D database (feed it to exportmap.sh)
#
# RUN IT (inside the robot container):
#     docker exec -it robot bash -lc '/root/ros2_ws/src/startmapping.sh'
#
# CONTINUE a previous session (incremental mapping — appends to the saved
# src/maps/rtabmap.db instead of starting fresh; start the robot somewhere
# already covered by the old map so rtabmap can loop-close and merge):
#     docker exec -it robot bash -lc '/root/ros2_ws/src/startmapping.sh --continue'
#
# IMPORTANT: stop the separate camera container first so this script's camera
# node can open the RealSense (only one node can own the device):
#     docker stop realsense_camera
#
# Drive the robot slowly around the space (teleop) while this runs. Ctrl-C to
# save + stop.
#
set -o pipefail

# ============================ EDIT THESE ====================================
export ROS_DOMAIN_ID=0
CAM_NS="/camera/camera"          # realsense2_camera default namespace (check: ros2 topic list)
BASE_FRAME="base_link"           # Create 3 base frame
ODOM_TOPIC="/odom"               # published by the Create 3
MAP_TOPIC="/map"                 # rtabmap 2D grid (if empty on save, check: ros2 topic list | grep map)
MAP_DIR="/root/ros2_ws/src/maps" # outputs land here (== robot/Dockerfile/src/maps on the Pi)
MAP_NAME="my_map"

# Camera mounting offset relative to base_link, in METRES and RADIANS.
# MEASURE THIS on your robot — these are placeholders (camera 10cm forward,
# 15cm up, facing forward). A wrong offset warps the whole map.
CAM_X=0.15;  CAM_Y=0.0;  CAM_Z=0.05
CAM_ROLL=0.0; CAM_PITCH=0.0; CAM_YAW=0.0
# ============================================================================

DB_SRC="$HOME/.ros/rtabmap.db"   # rtabmap's live database ($HOME is /root)

# --continue / -c / --resume: append to the previously saved database
RESUME=0
case "${1:-}" in
  -c|--continue|--resume) RESUME=1 ;;
esac

source /opt/ros/humble/setup.bash
[ -f /root/ros2_ws/install/setup.bash ] && source /root/ros2_ws/install/setup.bash
mkdir -p "$MAP_DIR"

CAM_PID=""; TF_PID=""; RTAB_PID=""; SAVED=0

save_and_shutdown() {
  [ "$SAVED" = 1 ] && return; SAVED=1
  trap '' INT TERM    # absorb repeated Ctrl-C so the save can't be interrupted
  echo
  echo "==================================================================="
  echo "[startmapping] STOPPING — saving map + database. Do NOT press Ctrl-C."
  echo "==================================================================="

  # 1) 2D occupancy grid — do this while rtabmap is still alive (/map available)
  if [ -n "$RTAB_PID" ] && kill -0 "$RTAB_PID" 2>/dev/null; then
    echo "[startmapping]   saving 2D grid from $MAP_TOPIC ..."
    timeout 20 ros2 run nav2_map_server map_saver_cli \
        -t "$MAP_TOPIC" -f "$MAP_DIR/$MAP_NAME" \
        --ros-args -p save_map_timeout:=8.0 </dev/null \
      || echo "[startmapping]   WARN: 2D map save failed/timed out (check $MAP_TOPIC exists)"
  fi

  # 2) stop rtabmap (SIGINT flushes the database), force-kill if it lingers
  echo "[startmapping]   stopping rtabmap (flushing database)..."
  if [ -n "$RTAB_PID" ]; then
    kill -INT -"$RTAB_PID" 2>/dev/null
    for _ in $(seq 1 12); do kill -0 "$RTAB_PID" 2>/dev/null || break; sleep 1; done
    kill -KILL -"$RTAB_PID" 2>/dev/null
  fi

  # 3) copy the database somewhere persistent (bind-mounted to the Pi),
  #    keeping one backup of the previous version
  if [ -f "$DB_SRC" ]; then
    if [ -f "$MAP_DIR/rtabmap.db" ]; then
      cp -f "$MAP_DIR/rtabmap.db" "$MAP_DIR/rtabmap.db.bak"
      echo "[startmapping]   previous database backed up -> $MAP_DIR/rtabmap.db.bak"
    fi
    cp -f "$DB_SRC" "$MAP_DIR/rtabmap.db"
    echo "[startmapping]   saved database -> $MAP_DIR/rtabmap.db"
  else
    echo "[startmapping]   WARN: $DB_SRC not found — database not saved"
  fi

  # 4) stop camera + static TF (SIGINT, then force-kill anything left)
  for _p in "$CAM_PID" "$TF_PID"; do [ -n "$_p" ] && kill -INT -"$_p" 2>/dev/null; done
  sleep 2
  for _p in "$CAM_PID" "$TF_PID"; do [ -n "$_p" ] && kill -KILL -"$_p" 2>/dev/null; done

  echo "[startmapping] done. Outputs in $MAP_DIR (Pi: robot/Dockerfile/src/maps/)"
  echo "[startmapping] export a cloud/mesh with:  ./src/exportmap.sh"
  exit 0
}
trap save_and_shutdown INT TERM

# Launch children via setsid (own process groups) so the terminal's Ctrl-C hits
# only THIS script — the trap then controls shutdown order (save, THEN kill).
echo "[startmapping] 1/3 launching RealSense with aligned depth..."
setsid ros2 launch realsense2_camera rs_launch.py \
    depth_module.depth_profile:=640x480x15 \
    rgb_camera.color_profile:=640x480x15 \
    align_depth.enable:=true \
    enable_gyro:=false enable_accel:=false &
CAM_PID=$!

echo "[startmapping] 2/3 static TF ${BASE_FRAME} -> camera_link (edit CAM_* above)..."
setsid ros2 run tf2_ros static_transform_publisher \
    --x "$CAM_X" --y "$CAM_Y" --z "$CAM_Z" \
    --roll "$CAM_ROLL" --pitch "$CAM_PITCH" --yaw "$CAM_YAW" \
    --frame-id "$BASE_FRAME" --child-frame-id camera_link &
TF_PID=$!

echo "[startmapping] waiting for camera to come up..."
sleep 6

# fresh run: wipe the working db on start. --continue: restore the saved db
# into rtabmap's working location and append to it (multi-session mapping).
RTAB_ARGS="--delete_db_on_start"
if [ "$RESUME" = 1 ]; then
  if [ -f "$MAP_DIR/rtabmap.db" ]; then
    echo "[startmapping] 3/3 resuming from $MAP_DIR/rtabmap.db ($(du -h "$MAP_DIR/rtabmap.db" | cut -f1))..."
    mkdir -p "$(dirname "$DB_SRC")"
    cp -f "$MAP_DIR/rtabmap.db" "$DB_SRC"
    RTAB_ARGS=""
  else
    echo "[startmapping] WARN: --continue given but $MAP_DIR/rtabmap.db not found — starting fresh"
  fi
else
  echo "[startmapping] 3/3 launching rtabmap (mapping mode, fresh database)..."
fi
setsid ros2 launch rtabmap_launch rtabmap.launch.py \
    rtabmap_args:="$RTAB_ARGS" \
    frame_id:="$BASE_FRAME" \
    odom_topic:="$ODOM_TOPIC" \
    visual_odometry:=false \
    subscribe_depth:=true \
    rgb_topic:="$CAM_NS/color/image_raw" \
    depth_topic:="$CAM_NS/aligned_depth_to_color/image_raw" \
    camera_info_topic:="$CAM_NS/color/camera_info" \
    approx_sync:=true \
    qos:=2 \
    rviz:=false \
    rtabmap_viz:=false \
    use_sim_time:=false &
RTAB_PID=$!

echo "[startmapping] mapping... drive the robot around slowly. Ctrl-C to save & stop."
wait "$RTAB_PID"          # if rtabmap dies on its own, still save what we have
save_and_shutdown
