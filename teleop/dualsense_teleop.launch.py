#  DualSense bluetooth teleop: joy_node -> teleop_twist_joy -> /cmd_vel
#
#     ros2 launch /robot/teleop/dualsense_teleop.launch.py
#
#  optional: remap the output topic
#     ros2 launch /robot/teleop/dualsense_teleop.launch.py cmd_vel_topic:=/diff_drive/cmd_vel

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('cmd_vel_topic', default_value='/cmd_vel'),

        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            parameters=[{
                'device_id': 0,
                'deadzone': 0.1,
                'autorepeat_rate': 20.0,
            }],
        ),

        Node(
            package='teleop_twist_joy',
            executable='teleop_node',
            name='teleop_twist_joy_node',
            parameters=['/robot/teleop/dualsense.yaml'],
            remappings=[('/cmd_vel', LaunchConfiguration('cmd_vel_topic'))],
        ),

        # triangle = dock, circle = undock (Create 3 actions)
        ExecuteProcess(
            cmd=['python3', '/robot/teleop/dock_buttons.py'],
            output='screen',
        ),
    ])
