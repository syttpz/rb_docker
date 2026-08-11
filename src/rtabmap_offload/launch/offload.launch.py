"""Server-side offloaded RTAB-Map pipeline.

    robot                          corelink                    server (this)
    ----------------------------   ---------   -------------------------------
    /camera/.../color/image_raw    --UDP-->    color_image_receiver  -.
    /camera/.../aligned_depth...   --UDP-->    depth_image_receiver  -+-> rgbd_sync
    /camera/.../color/camera_info  --UDP-->    camera_info_receiver  -'      |
                                                                             v
                                                              rgbd_odometry -> rtabmap

Every receiver is a ros2_bridge_node in `from_corelink` direction; the mapping
nodes come from rtabmap_ros. There is deliberately no ROS 2 node of our own in
this package -- the old rtabmap_offload_node never existed.

Frames: `frame_id` defaults to the RGB *optical* frame, which is also the
frame_id carried by the incoming images. That makes the tf tree self-contained
(rgbd_odometry publishes odom->frame_id, rtabmap publishes map->odom) so
neither /tf nor /tf_static has to cross the network. The resulting map is in
optical convention (z forward, y down) -- fine for transport experiments, but
set frame_id to a real base frame once /tf_static is bridged.

Clock: defaults to wall clock. The bag timestamps are from 2011/2012, which is
harmless here because nothing compares a stamp against now() -- there are no
external tf lookups. Set use_sim_time:=true AND bridge_clock:=true (and bridge
/clock on the robot side too) if you need sim time; with use_sim_time:=true and
no /clock arriving, every node blocks forever.
"""

import os
from datetime import datetime

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

# rmw_qos_reliability_policy_t: 0 = system default, 1 = reliable, 2 = best effort.
QOS_BEST_EFFORT = '2'

RGB_TOPIC = '/camera/camera/color/image_raw'
DEPTH_TOPIC = '/camera/camera/aligned_depth_to_color/image_raw'
INFO_TOPIC = '/camera/camera/color/camera_info'


def _receiver(name, topic, msgtype, params_file, protocol, reliability):
    """One ros2_bridge_node pulling a single stream off Corelink.

    The params file uses a `/**:` wildcard section, so it still applies after
    the node is renamed -- with a `ros2_bridge_node:` section it would not, and
    topic.direction would silently fall back to its "to_corelink" default.

    on_exit=Shutdown() because an unreachable Corelink makes the bridge throw
    std::bad_function_call and abort. Without it the mapping nodes keep running
    on an empty topic and the pod reports Running while receiving nothing;
    with it the container exits and k8s restarts (or visibly CrashLoops).
    """
    return Node(
        package='ros2_bridge_node',
        executable='ros2_bridge_node',
        name=name,
        output='screen',
        on_exit=Shutdown(reason=f'{name} exited'),
        parameters=[
            params_file,
            {
                'topic.name': topic,
                'topic.type': msgtype,
                'topic.direction': 'from_corelink',
                'corelink.data_protocol': protocol,
                'qos.reliability': reliability,
            },
        ],
    )


def generate_launch_description():
    bridge_share = get_package_share_directory('ros2_bridge_node')
    default_params = os.path.join(bridge_share, 'config', 'server_side.yaml')

    params_file = LaunchConfiguration('params_file')
    protocol = LaunchConfiguration('protocol')
    reliability = LaunchConfiguration('reliability')
    frame_id = LaunchConfiguration('frame_id')
    use_sim_time = LaunchConfiguration('use_sim_time')
    approx_sync_max_interval = LaunchConfiguration('approx_sync_max_interval')
    queue_size = LaunchConfiguration('queue_size')

    # RTAB-Map only flushes working memory to the database on SIGTERM, so a
    # fixed filename plus delete-on-start meant the completed map from run N was
    # destroyed by the startup of run N+1 before it could be copied off the PVC.
    # One file per run instead: the map survives, and "a fresh database per run"
    # (md/thesis-research-plan.md §7) still holds.
    default_run_id = os.environ.get('RUN_ID') or datetime.now().strftime('%Y%m%d-%H%M%S')
    database_path = ParameterValue(
        [LaunchConfiguration('database_dir'), '/rtabmap_',
         LaunchConfiguration('run_id'), '.db'],
        value_type=str)

    # Launch substitutions evaluate to strings, so anything that is not a string
    # parameter has to be wrapped or the node rejects it as the wrong type.
    qos = ParameterValue(
        PythonExpression(
            ["'", QOS_BEST_EFFORT, "' if '", reliability, "' == 'best_effort' else '1'"]),
        value_type=int)
    max_interval = ParameterValue(approx_sync_max_interval, value_type=float)
    queue = ParameterValue(queue_size, value_type=int)

    common = {'use_sim_time': ParameterValue(use_sim_time, value_type=bool)}

    args = [
        DeclareLaunchArgument(
            'params_file', default_value=default_params,
            description='Corelink params for the receivers (from_corelink side)'),
        DeclareLaunchArgument(
            'protocol', default_value='udp',
            description='Corelink data protocol: udp | tcp | websocket'),
        DeclareLaunchArgument(
            'reliability', default_value='best_effort',
            description='ROS QoS on both the receivers and the rtabmap nodes; '
                        'these must agree or no data flows'),
        DeclareLaunchArgument(
            'frame_id', default_value='openni_rgb_optical_frame',
            description='Fixed frame of the camera. Defaults to the TUM bag RGB '
                        'optical frame so no tf has to cross the network'),
        DeclareLaunchArgument(
            'use_sim_time', default_value='false',
            description='Requires bridge_clock:=true and /clock bridged from the '
                        'robot, otherwise every node blocks forever'),
        DeclareLaunchArgument(
            'bridge_clock', default_value='false',
            description='Also receive /clock over Corelink'),
        DeclareLaunchArgument(
            'run_id', default_value=default_run_id,
            description='Names the database, so every pod start writes its own. '
                        'Defaults to $RUN_ID, else a launch-time timestamp'),
        DeclareLaunchArgument(
            'database_dir', default_value='/root/.ros',
            description='The PVC mount point in k8s'),
        DeclareLaunchArgument(
            'delete_db_on_start', default_value='false',
            description='Off because run_id already gives each run a fresh file. '
                        'Turning it on would delete the previous run\'s map before '
                        'it could be copied off the volume'),
        DeclareLaunchArgument(
            'approx_sync_max_interval', default_value='0.02',
            description='RGB-D pairing window in seconds. The TUM bags pair at '
                        'median 11.9 ms / p95 17.6 ms'),
        DeclareLaunchArgument(
            'queue_size', default_value='30',
            description='Deep enough to ride out reassembly jitter'),
    ]

    receivers = [
        _receiver('color_image_receiver', RGB_TOPIC,
                  'sensor_msgs/msg/Image', params_file, protocol, reliability),
        _receiver('depth_image_receiver', DEPTH_TOPIC,
                  'sensor_msgs/msg/Image', params_file, protocol, reliability),
        _receiver('camera_info_receiver', INFO_TOPIC,
                  'sensor_msgs/msg/CameraInfo', params_file, protocol, reliability),
    ]

    clock_receiver = Node(
        package='ros2_bridge_node',
        executable='ros2_bridge_node',
        name='clock_receiver',
        output='screen',
        condition=IfCondition(LaunchConfiguration('bridge_clock')),
        parameters=[
            params_file,
            {
                'topic.name': '/clock',
                'topic.type': 'rosgraph_msgs/msg/Clock',
                'topic.direction': 'from_corelink',
                'corelink.data_protocol': protocol,
                'qos.reliability': 'reliable',
            },
        ],
    )

    # Pairs RGB + depth + camera_info into one RGBDImage so odometry and mapping
    # subscribe to a single already-synchronised stream instead of racing on
    # three independently-reassembled topics.
    rgbd_sync = Node(
        package='rtabmap_sync', executable='rgbd_sync', name='rgbd_sync',
        output='screen',
        parameters=[common, {
            'approx_sync': True,
            'approx_sync_max_interval': max_interval,
            'sync_queue_size': queue,
            'qos': qos,
            'qos_camera_info': qos,
        }],
        remappings=[
            ('rgb/image', RGB_TOPIC),
            ('depth/image', DEPTH_TOPIC),
            ('rgb/camera_info', INFO_TOPIC),
            ('rgbd_image', '/rgbd_image'),
        ],
    )

    # No wheel odometry crosses the network (the TUM bags have none), so pose
    # comes from visual odometry here on the server.
    rgbd_odometry = Node(
        package='rtabmap_odom', executable='rgbd_odometry', name='rgbd_odometry',
        output='screen',
        parameters=[common, {
            'frame_id': frame_id,
            'odom_frame_id': 'odom',
            'subscribe_rgbd': True,
            'approx_sync': True,
            'sync_queue_size': queue,
            'qos': qos,
            'publish_tf': True,
            # Nothing external to wait for -- the tf tree is produced here.
            'wait_for_transform': 0.0,
        }],
        remappings=[
            ('rgbd_image', '/rgbd_image'),
            ('odom', '/odom'),
        ],
    )

    # `-d` (delete database on start) is a command-line flag, not a parameter,
    # and a list element cannot be included conditionally -- passing an empty
    # string instead would leave rtabmap parsing a bogus argv entry. So the node
    # is declared twice under opposite conditions; exactly one ever starts.
    def _rtabmap(name, condition, arguments):
        return Node(
            package='rtabmap_slam', executable='rtabmap', name=name,
            output='screen',
            condition=condition,
            parameters=[common, {
                'frame_id': frame_id,
                'odom_frame_id': 'odom',
                'subscribe_rgbd': True,
                'subscribe_depth': False,
                'subscribe_scan': False,
                'approx_sync': True,
                'sync_queue_size': queue,
                'qos': qos,
                'database_path': database_path,
                'wait_for_transform': 0.0,
            }],
            remappings=[
                ('rgbd_image', '/rgbd_image'),
                ('odom', '/odom'),
            ],
            arguments=arguments,
        )

    delete_db = LaunchConfiguration('delete_db_on_start')
    rtabmap_fresh = _rtabmap('rtabmap', IfCondition(delete_db), ['-d'])
    rtabmap_resume = _rtabmap('rtabmap', UnlessCondition(delete_db), [])

    return LaunchDescription(
        args + receivers
        + [clock_receiver, rgbd_sync, rgbd_odometry, rtabmap_fresh, rtabmap_resume])
