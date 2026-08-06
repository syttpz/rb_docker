#!/usr/bin/env bash
# Build ros2_bridge_node with plain cmake/make into ./build/ros2_bridge_node.
# (Standalone build, not colcon — matches running ./build/ros2_bridge_node directly.)
# Arch-aware: overrides the x86-only corelink lib paths so it also builds on
# arm64 (the Pi). Incremental: safe to run every time, only rebuilds changes.
set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$HERE/build"

# Source ROS before `set -u`: its setup scripts reference unbound vars.
source /opt/ros/humble/setup.bash
set -u

# e.g. x86_64-linux-gnu on the laptop, aarch64-linux-gnu on the Pi
MULTIARCH="$(gcc -print-multiarch 2>/dev/null || echo x86_64-linux-gnu)"
LIBDIR="/usr/lib/$MULTIARCH"

echo "[build] arch=$MULTIARCH  build_dir=$BUILD_DIR"
cmake -S "$HERE" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCORELINK_LWS_LIB_PATH="$LIBDIR" \
    -DCORELINK_OPENSSL_LIB_PATH="$LIBDIR" \
    -DCORELINK_OPENSSL_BIN_PATH="$LIBDIR"
cmake --build "$BUILD_DIR" -j"$(nproc)"

echo "[build] done -> $BUILD_DIR/ros2_bridge_node"
