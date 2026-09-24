#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动节点2（真机桥接 real_robot_bridge.py）。

用法（需在 litearm-python venv + ROS2 Humble 环境）：
  ros2 launch bridge.launch.py
  ros2 launch bridge.launch.py ip:=192.168.31.139
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    ip = LaunchConfiguration("ip", default="192.168.31.139")

    ip_arg = DeclareLaunchArgument(
        "ip", default_value="192.168.31.139",
        description="litearm-server 所在工控机 IP")

    # real_robot_bridge.py 是独立脚本，不在 ROS2 包里，用 ExecuteProcess 直接跑
    bridge = ExecuteProcess(
        cmd=[
            "python3",
            "/home/qql/sl/litearm_sync_release/real_robot_bridge.py",
            "--endpoint", ["tcp/", ip, ":7447"],
        ],
        output="screen",
        name="litearm_real_robot_bridge",
    )

    return LaunchDescription([ip_arg, bridge])
