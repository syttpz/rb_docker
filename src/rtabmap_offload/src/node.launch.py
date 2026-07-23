from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
	namespace_arg = DeclareLaunchArgument(
		'namespace',
		default_value='',
		description='Namespace for the offload RTAB-Map node'
	)

	use_sim_time_arg = DeclareLaunchArgument(
		'use_sim_time',
		default_value='false',
		description='Use simulation clock if true'
	)

	offload_node = Node(
		package='rtabmap_offload',
		executable='rtabmap_offload_node',
		name='rtabmap_offload',
		namespace=LaunchConfiguration('namespace'),
		output='screen',
		parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
	)

	return LaunchDescription([
		namespace_arg,
		use_sim_time_arg,
		offload_node,
	])
