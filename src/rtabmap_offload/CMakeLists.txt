cmake_minimum_required(VERSION 3.20)
project(rtabmap_offload)

find_package(ament_cmake REQUIRED)

# Launch-only package: every node it starts lives in ros2_bridge_node or
# rtabmap_ros, so there is nothing to compile here.
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
