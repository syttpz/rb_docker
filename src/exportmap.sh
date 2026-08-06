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

# ---------------------------------------------------------------------------
# 1) 3D point cloud + textured mesh (rtabmap-export only does 3D, not 2D grid)
# ---------------------------------------------------------------------------
echo "[exportmap] exporting cloud + mesh from: $DB"
rtabmap-export --cloud --mesh --texture --texture_count 4 --texture_size 4096 --output_dir "$OUT_DIR" "$DB"

# ---------------------------------------------------------------------------
# 2) 2D occupancy grid.
#    startmapping.sh saves it live at shutdown -> my_map.pgm / my_map.yaml.
#    If that step timed out / is missing, regenerate it offline from the db
#    with `rtabmap-reprocess -g2` (assembles the grid -> <output>_map.pgm).
# ---------------------------------------------------------------------------
if ls "$OUT_DIR"/*_map.pgm "$OUT_DIR"/my_map.pgm >/dev/null 2>&1; then
  echo "[exportmap] 2D grid already present (saved live during mapping):"
  ls -1 "$OUT_DIR"/*_map.pgm "$OUT_DIR"/my_map.pgm 2>/dev/null
else
  echo "[exportmap] no live 2D grid found — regenerating from database (rtabmap-reprocess -g2)..."
  TMP_DIR="$OUT_DIR/.grid_tmp"
  rm -rf "$TMP_DIR"; mkdir -p "$TMP_DIR"
  if rtabmap-reprocess -g2 "$DB" "$TMP_DIR/out.db"; then
    PGM="$(ls -1 "$TMP_DIR"/*_map.pgm 2>/dev/null | head -n1)"
    if [ -n "$PGM" ] && [ -f "$PGM" ]; then
      mv -f "$PGM" "$OUT_DIR/grid_map.pgm"
      # move the matching yaml too, if reprocess produced one
      YAML="${PGM%_map.pgm}_map.yaml"
      [ -f "$YAML" ] && mv -f "$YAML" "$OUT_DIR/grid_map.yaml"
      echo "[exportmap]   saved 2D grid -> $OUT_DIR/grid_map.pgm"
    else
      echo "[exportmap]   WARN: rtabmap-reprocess produced no grid pgm (db may have no 2D grid data)"
    fi
  else
    echo "[exportmap]   WARN: rtabmap-reprocess failed — 2D grid not regenerated"
  fi
  rm -rf "$TMP_DIR"
fi

echo "[exportmap] done. Files in $OUT_DIR:"
ls -la "$OUT_DIR"/*.ply "$OUT_DIR"/*.obj "$OUT_DIR"/*.mtl "$OUT_DIR"/*material*.png \
       "$OUT_DIR"/*.pgm "$OUT_DIR"/*.yaml 2>/dev/null
