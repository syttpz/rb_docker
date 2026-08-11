"""Robot side of the offload test: push RGB, depth and camera_info to Corelink.

The counterpart of rtabmap_offload/offload.launch.py. run_robot.sh only bridges
a single topic, which is not enough to feed RTAB-Map.

Typical use with a replayed bag (in another shell):

    ros2 bag play datasets/fr3_long_office_rs --rate 0.2

    ros2 launch ros2_bridge_node robot_senders.launch.py \
        credentials_file:=/path/to/config/credentials.yaml

--rate 0.2 turns the bag's 30 Hz into 6 Hz on the wire, matching the
640x480x6 profile docker-compose.yml runs the RealSense at. Note it does not
decimate: all 30 Hz frames are still sent, just stretched out, so the
inter-frame baseline stays 30 Hz-dense. Fine for transport measurements,
not equivalent to true 6 Hz sampling for SLAM.

Pacing defaults assume that 6 Hz wire rate. A 921,600-byte RGB frame is ~57
fragments at 16 KB, so the gap is (166667 us / 57) / 2 ~ 1400 us; depth is
614,400 bytes ~ 38 fragments -> ~2100 us. Raise `rate` and these must come
down proportionally or the pacer queue overflows.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

RGB_TOPIC = '/camera/camera/color/image_raw'
DEPTH_TOPIC = '/camera/camera/aligned_depth_to_color/image_raw'
INFO_TOPIC = '/camera/camera/color/camera_info'


def generate_launch_description():
    share = get_package_share_directory('ros2_bridge_node')
    default_params = os.path.join(share, 'config', 'robot_side.yaml')
    default_creds = os.path.join(share, 'config', 'credentials.yaml')

    params_file = LaunchConfiguration('params_file')
    credentials_file = LaunchConfiguration('credentials_file')
    protocol = LaunchConfiguration('protocol')
    reliability = LaunchConfiguration('reliability')
    queue_max = ParameterValue(
        LaunchConfiguration('pacing_queue_max'), value_type=int)

    def sender(name, topic, msgtype, pacing_arg):
        return Node(
            package='ros2_bridge_node',
            executable='ros2_bridge_node',
            name=name,
            output='screen',
            on_exit=Shutdown(reason=f'{name} exited'),
            parameters=[
                params_file,
                credentials_file,
                {
                    'topic.name': topic,
                    'topic.type': msgtype,
                    'topic.direction': 'to_corelink',
                    'corelink.data_protocol': protocol,
                    'qos.reliability': reliability,
                    'send.pacing_us': ParameterValue(
                        LaunchConfiguration(pacing_arg), value_type=int),
                    'send.pacing_queue_max': queue_max,
                },
            ],
        )

    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_params),
        DeclareLaunchArgument(
            'credentials_file', default_value=default_creds,
            description='Gitignored; copy credentials.yaml.example and fill in. '
                        'Loaded after params_file so it wins on shared keys'),
        DeclareLaunchArgument('protocol', default_value='udp'),
        DeclareLaunchArgument(
            'reliability', default_value='best_effort',
            description='Must match the server launch, or no data flows'),
        DeclareLaunchArgument(
            'rgb_pacing_us', default_value='1400',
            description='Fragment gap for RGB (~57 fragments/frame at 6 Hz)'),
        DeclareLaunchArgument(
            'depth_pacing_us', default_value='2100',
            description='Fragment gap for depth (~38 fragments/frame at 6 Hz)'),
        DeclareLaunchArgument(
            'info_pacing_us', default_value='0',
            description='CameraInfo is a single fragment; no pacing needed'),
        DeclareLaunchArgument(
            'pacing_queue_max', default_value='256',
            description='~4 RGB frames of slack; the 128 default is under 3'),
        DeclareLaunchArgument(
            'bridge_clock', default_value='false',
            description='Send /clock too, for a server running use_sim_time'),

        sender('color_image_sender', RGB_TOPIC,
               'sensor_msgs/msg/Image', 'rgb_pacing_us'),
        sender('depth_image_sender', DEPTH_TOPIC,
               'sensor_msgs/msg/Image', 'depth_pacing_us'),
        sender('camera_info_sender', INFO_TOPIC,
               'sensor_msgs/msg/CameraInfo', 'info_pacing_us'),

        Node(
            package='ros2_bridge_node',
            executable='ros2_bridge_node',
            name='clock_sender',
            output='screen',
            condition=IfCondition(LaunchConfiguration('bridge_clock')),
            on_exit=Shutdown(reason='clock_sender exited'),
            parameters=[
                params_file,
                credentials_file,
                {
                    'topic.name': '/clock',
                    'topic.type': 'rosgraph_msgs/msg/Clock',
                    'topic.direction': 'to_corelink',
                    'corelink.data_protocol': protocol,
                    'qos.reliability': 'reliable',
                },
            ],
        ),
    ])
