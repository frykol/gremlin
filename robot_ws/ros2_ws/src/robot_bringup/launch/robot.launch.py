import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    bringup_share = get_package_share_directory('robot_bringup')
    twist_mux_config = os.path.join(bringup_share, 'config', 'twist_mux.yaml')
    slam_toolbox_config = os.path.join(bringup_share, 'config', 'slam_toolbox.yaml')

    nav_arg = DeclareLaunchArgument(
        'nav', default_value='false',
        description='Launch Nav2 bringup (requires an existing map from slam_toolbox)'
    )
    voice_device_arg = DeclareLaunchArgument(
        'voice_device', default_value='auto',
        description='Audio input device index for voice_node, or "auto" to detect ReSpeaker by name'
    )

    voice_node = Node(
        package='voice_node',
        executable='voice_node',
        name='voice_node',
        output='screen',
        arguments=['--model', '/robot/model', '--device', LaunchConfiguration('voice_device')],
    )

    gesture_node = Node(
        package='gesture_node',
        executable='gesture_node',
        name='gesture_node',
        output='screen',
    )

    motor_driver = Node(
        package='motor_driver',
        executable='motor_driver',
        name='motor_driver',
        output='screen',
    )

    twist_mux = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        output='screen',
        parameters=[twist_mux_config],
        remappings=[('/cmd_vel_out', '/cmd_vel')],
    )

    # TODO: confirm the LIDAR point cloud topic once the Unitree L2 driver
    # is running (e.g. `ros2 topic list` -> /unilidar/cloud) and update
    # the remap below.
    pointcloud_to_laserscan = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        output='screen',
        remappings=[('cloud_in', '/unilidar/cloud'), ('scan', '/scan')],
        parameters=[{
            'target_frame': 'laser_link',
            'min_height': -0.1,
            'max_height': 0.3,
            'range_min': 0.1,
            'range_max': 20.0,
        }],
    )

    slam_toolbox = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[slam_toolbox_config],
    )

    # TODO: measure and set the actual mounting offsets (x y z yaw pitch
    # roll) for the LIDAR and OAK-D once the chassis is final.
    laser_static_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_to_laser_tf',
        arguments=['0', '0', '0.15', '0', '0', '0', 'base_link', 'laser_link'],
    )

    oak_static_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_to_oak_tf',
        arguments=['0.1', '0', '0.1', '0', '0', '0', 'base_link', 'oak_camera_link'],
    )

    nav2_bringup_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('nav2_bringup'), 'launch', 'bringup_launch.py')
        ),
        condition=IfCondition(LaunchConfiguration('nav')),
    )

    return LaunchDescription([
        nav_arg,
        voice_device_arg,
        voice_node,
        gesture_node,
        motor_driver,
        twist_mux,
        pointcloud_to_laserscan,
        slam_toolbox,
        laser_static_tf,
        oak_static_tf,
        nav2_bringup_launch,
    ])
