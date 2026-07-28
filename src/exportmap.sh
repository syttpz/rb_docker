#!/usr/bin/env bash
#
# exportmap.sh — export an assembled point cloud + mesh (PLY) from an
# rtabmap database produced by startmapping.sh.
#
# RUN IT (inside the robot container):
#     docker exec -it robot bash -lc '/root/ros2_ws/src/exportmap.sh'
#   optionally pass a run folder or a specific database:
#     ./src/exportmap.sh /root/ros2_ws/src/maps/map_20260728_120000
#     ./src/exportmap.sh /root/ros2_ws/src/maps/map_20260728_120000/rtabmap.db
#
# With no argument, the newest map_* folder is used.
# Output PLYs land next to the database (in the run folder).
#
set -o pipefail
source /opt/ros/humble/setup.bash

MAP_DIR="/root/ros2_ws/src/maps"

ARG="${1:-}"
if [ -z "$ARG" ]; then
  # newest run folder
  RUN_DIR="$(ls -1d "$MAP_DIR"/map_* 2>/dev/null | sort | tail -n1)"
  DB="$RUN_DIR/rtabmap.db"
elif [ -d "$ARG" ]; then
  DB="$ARG/rtabmap.db"
else
  DB="$ARG"
fi

if [ ! -f "$DB" ]; then
  echo "[exportmap] database not found: $DB"
  echo "[exportmap] run startmapping.sh first, or pass a run folder / .db path as an argument."
  exit 1
fi
OUT_DIR="$(dirname "$DB")"

echo "[exportmap] exporting cloud + mesh from: $DB"
rtabmap-export --cloud --mesh --texture --texture_count 4 --texture_size 4096 --output_dir "$OUT_DIR" "$DB"

echo "[exportmap] done. Files in $OUT_DIR:"
ls -la "$OUT_DIR"/*.ply "$OUT_DIR"/*.obj "$OUT_DIR"/*.mtl "$OUT_DIR"/*material*.png 2>/dev/null
