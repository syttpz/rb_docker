#!/usr/bin/env bash
#
# exportmap.sh — export an assembled point cloud + mesh (PLY) from an
# rtabmap database produced by startmapping.sh.
#
# RUN IT (inside the robot container):
#     docker exec -it robot bash -lc '/root/ros2_ws/src/exportmap.sh'
#   optionally pass a specific database:
#     ./src/exportmap.sh /root/ros2_ws/src/maps/rtabmap.db
#
# Output PLYs land next to the database (src/maps/, bind-mounted to the Pi).
#
set -o pipefail
source /opt/ros/humble/setup.bash

DB="${1:-/root/ros2_ws/src/maps/rtabmap.db}"
if [ ! -f "$DB" ]; then
  echo "[exportmap] database not found: $DB"
  echo "[exportmap] run startmapping.sh first, or pass the .db path as an argument."
  exit 1
fi
OUT_DIR="$(dirname "$DB")"

echo "[exportmap] exporting cloud + mesh from: $DB"
rtabmap-export --cloud --mesh --texture --texture_count 4 --texture_size 4096 --output_dir "$OUT_DIR" "$DB"

echo "[exportmap] done. Files in $OUT_DIR:"
ls -la "$OUT_DIR"/*.ply "$OUT_DIR"/*.obj "$OUT_DIR"/*.mtl "$OUT_DIR"/*material*.png 2>/dev/null
