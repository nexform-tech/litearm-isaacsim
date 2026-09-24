#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点 1 · API 指令发布器：手动指定 SDK API，打包成 JSON 指令发布。

三节点单向数据流：
  publish_api.py  ──{api, args}──▶  real_robot_bridge.py  ──实时关节角──▶  isaac_sim_node.py
  （只发指令，不连真机）            （反射调 SDK → 真机；发状态）         （订阅状态 → 驱动 USD）

本节点【不连接真机、不依赖 litearm SDK】，只把你要执行的 API 及其参数
打包成 JSON 通过 std_msgs/String 发布到 /litearm/api_cmd。真机桥接节点
收到后反射调用 arm.<api>(**args)，真机动作，同时实时关节角经
/litearm/joint_state 流转到仿真，仿真跟着动。

用法示例：
  # 关节空间运动
  python3 publish_api.py --api movej --args '{"q_target":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'

  # 笛卡尔直线（目标位姿：位置+3x3旋转矩阵）
  python3 publish_api.py --api movel --args '{"pose_goal":[[0.4,-0.2,0.3],[[1,0,0],[0,1,0],[0,0,1]]],"speed":0.1}'

  # 纯计算：fk（返回末端位姿，不打日志到本节点，结果在节点2日志里）
  python3 publish_api.py --api fk --args '{"q":[0,0,0,0,0,0,0]}'

  # 力控/零重力（⚠️ 会让臂瘫软，人须扶住）
  python3 publish_api.py --api zero_gravity --args '{}'

  # 急停
  python3 publish_api.py --api request_stop --args '{}'

运行（在 litearm-python .venv 里，且已 source ROS2 Humble）：
  source /opt/ros/humble/setup.zsh
"""
import argparse
import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", required=True,
                    help="要执行的 SDK API 名，如 movej/movel/fk/zero_gravity/request_stop")
    ap.add_argument("--args", default="{}",
                    help="API 的 kwargs，JSON 字典，如 '{\"q_target\":[...],\"speed\":0.1}'")
    ap.add_argument("--topic", default="/litearm/api_cmd",
                    help="发布 API 指令的 topic")
    return ap.parse_args()


def main():
    args = parse_args()

    # 解析并校验 JSON
    try:
        kwargs = json.loads(args.args)
        if not isinstance(kwargs, dict):
            raise ValueError("--args 必须是 JSON 对象")
    except Exception as e:
        print(f"[错误] --args 解析失败: {e}")
        return

    rclpy.init()
    node = Node("litearm_publish_api")
    pub = node.create_publisher(String, args.topic, 10)

    cmd = json.dumps({"api": args.api, "args": kwargs})
    node.get_logger().info(f"[PUB] -> {cmd}")

    # 发布并等待订阅者完成 discovery（真机桥接节点须已在线）
    msg = String()
    msg.data = cmd
    deadline = node.get_clock().now() + rclpy.duration.Duration(seconds=15.0)
    published = False
    while rclpy.ok() and node.get_clock().now() < deadline:
        if pub.get_subscription_count() > 0:
            pub.publish(msg)
            node.get_logger().info(
                f"[PUB] 已送达，订阅者 {pub.get_subscription_count()} 个")
            published = True
            break
        rclpy.spin_once(node, timeout_sec=0.1)
    if not published:
        node.get_logger().warn("[PUB] 15s 内未匹配到订阅者，指令可能丢失")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
