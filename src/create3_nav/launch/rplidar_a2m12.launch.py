"""RPLIDAR A2M12 bringup for the Create 3.

Brings up the Slamtec driver (`rplidar_node` from ros-humble-rplidar-ros) and,
by default, a static transform placing the laser on the robot so the /scan is
usable by anything downstream (nav2 costmaps, slam_toolbox).

    ros2 launch create3_nav rplidar_a2m12.launch.py

A2M12-specific facts baked into the defaults:
  * serial_baudrate = 256000. The older A2M8 is 115200; using the wrong baud
    is the usual reason the device authenticates but publishes no /scan.
  * scan_mode is left EMPTY by default, which makes the driver use the mode
    the firmware reports as default. Forcing a named mode (e.g. Sensitivity)
    is rejected as "scan mode not supported / Can not start scan: 80008001"
    on units whose firmware doesn't advertise that exact name -- which is why
    the stock rplidar_ros a2m12 launch declares Sensitivity but never passes
    it. Override with scan_mode:=Standard|Sensitivity|Boost only if needed.

Serial port: defaults to /dev/ttyUSB0. Prefer the stable /dev/rplidar symlink
from config/99-rplidar.rules once that udev rule is installed on the host, so a
second USB-serial device can't steal ttyUSB0:

    ros2 launch create3_nav rplidar_a2m12.launch.py serial_port:=/dev/rplidar

Mounting: lidar_xyz / lidar_rpy are the laser pose in base_link and MUST be
measured on the real robot. Defaults assume the A2M12 sits on the Create 3 top
plate, centered, ~0.09 m up, pointing forward -- a placeholder to calibrate.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    channel_type = LaunchConfiguration('channel_type')
    serial_port = LaunchConfiguration('serial_port')
    serial_baudrate = LaunchConfiguration('serial_baudrate')
    frame_id = LaunchConfiguration('frame_id')
    inverted = LaunchConfiguration('inverted')
    angle_compensate = LaunchConfiguration('angle_compensate')
    scan_mode = LaunchConfiguration('scan_mode')
    scan_topic = LaunchConfiguration('scan_topic')
    base_frame = LaunchConfiguration('base_frame')

    args = [
        DeclareLaunchArgument('channel_type', default_value='serial'),
        DeclareLaunchArgument(
            'serial_port', default_value='/dev/ttyUSB0',
            description='Serial device. Use /dev/rplidar if the udev rule is installed'),
        DeclareLaunchArgument(
            'serial_baudrate', default_value='256000',
            description='A2M12 = 256000. Do NOT use 115200 (that is the A2M8)'),
        DeclareLaunchArgument(
            'frame_id', default_value='laser',
            description='tf frame the scan is published in'),
        DeclareLaunchArgument('inverted', default_value='false'),
        DeclareLaunchArgument('angle_compensate', default_value='true'),
        DeclareLaunchArgument(
            'scan_mode', default_value='',
            description='Empty = driver default (recommended). Named modes '
                        '(Standard|Sensitivity|Boost) fail on units that do '
                        'not advertise that exact name'),
        DeclareLaunchArgument(
            'scan_topic', default_value='/scan',
            description='Output LaserScan topic (nav2/slam_toolbox default is /scan)'),
        DeclareLaunchArgument(
            'publish_static_tf', default_value='true',
            description='Publish base_frame -> frame_id so the scan is on the robot. '
                        'Turn off if a URDF/robot_state_publisher already provides it'),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        # Laser pose in base_link -- MEASURE on the real robot.
        DeclareLaunchArgument('lidar_x', default_value='0.0'),
        DeclareLaunchArgument('lidar_y', default_value='0.0'),
        DeclareLaunchArgument('lidar_z', default_value='0.09'),
        DeclareLaunchArgument('lidar_yaw', default_value='0.0'),
        DeclareLaunchArgument('lidar_pitch', default_value='0.0'),
        DeclareLaunchArgument('lidar_roll', default_value='0.0'),
    ]

    rplidar = Node(
        package='rplidar_ros',
        executable='rplidar_node',
        name='rplidar_node',
        output='screen',
        parameters=[{
            'channel_type': channel_type,
            'serial_port': serial_port,
            'serial_baudrate': serial_baudrate,
            'frame_id': frame_id,
            'inverted': inverted,
            'angle_compensate': angle_compensate,
            'scan_mode': scan_mode,
        }],
        remappings=[('scan', scan_topic)],
    )

    # args order for static_transform_publisher: x y z yaw pitch roll parent child
    laser_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_link_to_laser',
        condition=IfCondition(LaunchConfiguration('publish_static_tf')),
        arguments=[
            LaunchConfiguration('lidar_x'), LaunchConfiguration('lidar_y'),
            LaunchConfiguration('lidar_z'), LaunchConfiguration('lidar_yaw'),
            LaunchConfiguration('lidar_pitch'), LaunchConfiguration('lidar_roll'),
            base_frame, frame_id,
        ],
    )

    return LaunchDescription(args + [rplidar, laser_tf])
