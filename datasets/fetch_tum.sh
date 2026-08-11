#!/usr/bin/env bash
# Fetch TUM RGB-D ROS 1 bags and convert them into RealSense-shaped ROS 2 bags.
# The bags themselves are gitignored; this script reproduces them from scratch.
#
#   ./fetch_tum.sh              # fr1_desk (smoke test) + fr3_long_office (main)
#   ./fetch_tum.sh fr1_desk     # just one
set -euo pipefail

cd "$(dirname "$0")"

declare -A SEQUENCES=(
  [fr1_desk]="freiburg1/rgbd_dataset_freiburg1_desk.bag"
  [fr1_room]="freiburg1/rgbd_dataset_freiburg1_room.bag"
  [fr2_pioneer_slam]="freiburg2/rgbd_dataset_freiburg2_pioneer_slam.bag"
  [fr3_long_office]="freiburg3/rgbd_dataset_freiburg3_long_office_household.bag"
)

BASE="https://cvg.cit.tum.de/rgbd/dataset"
TARGETS=("${@:-fr1_desk fr3_long_office}")
# shellcheck disable=SC2206
TARGETS=(${TARGETS[*]})

command -v rosbags-convert >/dev/null 2>&1 || \
  python3 -m pip install --user rosbags

mkdir -p ros1

for name in "${TARGETS[@]}"; do
  rel="${SEQUENCES[$name]:?unknown sequence '$name'}"
  bag="ros1/$(basename "$rel")"

  echo "==> $name"
  wget -c -O "$bag" "$BASE/$rel"

  if [[ -d "${name}_rs" ]]; then
    echo "    ${name}_rs already converted, skipping"
  else
    python3 prepare_tum_ros2.py --src "$bag" --dst "${name}_rs"
  fi
done

echo
echo "done. play with:"
echo "  ros2 bag play datasets/<name>_rs --clock"
