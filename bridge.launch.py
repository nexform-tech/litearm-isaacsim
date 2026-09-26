#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动节点2（真机桥接 real_robot_bridge.py）。

真机经 STM32 USB CDC 直连（litearm-python-gitee 薄协议 SDK），不走 server/IP。

用法（需 ROS2 Humble，且新 SDK 的 src 在 PYTHONPATH 里）：
  ros2 launch bridge.launch.py                       # 自动发现 CDC
  ros2 launch bridge.launch.py port:=/dev/ttyACM0    # 指定串口
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    port = LaunchConfiguration("port", default="")

    port_arg = DeclareLaunchArgument(
        "port", default_value="",
        description="STM32 CDC 串口（如 /dev/ttyACM0）；留空=自动发现 1d50:606f")

    # real_robot_bridge.py 是独立脚本，不在 ROS2 包里，用 ExecuteProcess 直接跑
    bridge = ExecuteProcess(
        cmd=[
            "python3",
            "/home/qql/sl/litearm_sync_release/real_robot_bridge.py",
            "--port", port,
        ],
        output="screen",
        name="litearm_real_robot_bridge",
    )

    return LaunchDescription([port_arg, bridge])
