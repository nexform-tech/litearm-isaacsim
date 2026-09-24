#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机桥接节点（节点 2）：订阅 API 指令 → 反射调 SDK 驱动真机；持续发布实时关节角。

三节点单向数据流：
  publish_api.py  ──{api, args}──▶  real_robot_bridge.py  ──实时关节角──▶  isaac_sim_node.py
  （只发指令）                      （反射调 SDK → 真机；发状态）          （订阅状态 → 驱动 USD）

职责：
  1. 订阅 /litearm/api_cmd（std_msgs/String，JSON: {"api": ..., "args": {...}}），
     反射调用 arm.<api>(**args) 驱动真机。指令在独立线程执行，
     因为运动类 API 会阻塞到完成，不能占用 spin 线程。
  2. 周期读取 arm.get_state()["q"]（约 50Hz 状态广播缓存），
     发布到 /litearm/joint_state（sensor_msgs/JointState），
     仿真节点订阅后逐帧驱动 USD 关节。无论动作由哪个 API 产生，仿真都跟随。

⚠️ 真机会真实运动！力控/零重力类 API 会让臂瘫软，人须扶住。

运行（在 litearm-python 的 .venv 里，且已 source ROS2 Humble）：
  python3 real_robot_bridge.py --endpoint tcp/192.168.31.139:7447
"""
import argparse
import json
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

import litearm

# 7 轴关节名（与真机/仿真一致）
JOINT_NAMES = ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Joint6", "Joint7"]


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", default="tcp/192.168.31.139:7447",
                    help="litearm-server 的端点")
    ap.add_argument("--arm-id", default="armA", help="Arm 标识")
    ap.add_argument("--cmd-topic", default="/litearm/api_cmd",
                    help="订阅 API 指令的 topic")
    ap.add_argument("--state-topic", default="/litearm/joint_state",
                    help="发布真机实时关节状态的 topic")
    ap.add_argument("--rate", type=float, default=50.0,
                    help="状态发布频率 Hz（匹配状态广播，默认 50）")
    return ap.parse_args()


class RealRobotBridge(Node):
    def __init__(self, args):
        super().__init__("litearm_real_robot_bridge")
        self.arm = litearm.Arm(endpoint=args.endpoint, arm_id=args.arm_id)
        self.get_logger().info(f"[SDK] 已连接 {args.endpoint}")

        # 实时状态发布：真机怎么动，仿真怎么动
        self.state_pub = self.create_publisher(JointState, args.state_topic, 10)
        self._state_timer = self.create_timer(1.0 / args.rate, self._publish_state)
        self.get_logger().info(
            f"[PUB] 发布实时关节状态 {args.state_topic} @ {args.rate}Hz")

        # API 指令订阅：反射调 SDK
        self.cmd_sub = self.create_subscription(
            String, args.cmd_topic, self._on_cmd, 10)
        self.get_logger().info(f"[SUB] 订阅 API 指令 {args.cmd_topic}")

    def _publish_state(self):
        st = self.arm.get_state()
        if st is None or not st.get("q"):
            return
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = [float(x) for x in st["q"][:7]]
        self.state_pub.publish(msg)

    def _on_cmd(self, msg: String):
        """收到 API 指令，放到独立线程执行，避免阻塞 spin 线程。"""
        try:
            cmd = json.loads(msg.data)
            api = cmd.get("api")
            kwargs = cmd.get("args", {})
        except Exception as e:
            self.get_logger().error(f"[CMD] 指令解析失败: {e}")
            return
        if not api or not hasattr(self.arm, api):
            self.get_logger().error(f"[CMD] 未知 API: {api!r}")
            return
        self.get_logger().info(f"[CMD] 执行 {api} {kwargs}")
        t = threading.Thread(target=self._exec, args=(api, kwargs), daemon=True)
        t.start()

    def _exec(self, api, kwargs):
        try:
            result = getattr(self.arm, api)(**kwargs)
            self.get_logger().info(f"[CMD] {api} 完成 = {result}")
        except Exception as e:
            self.get_logger().error(f"[CMD] {api} 异常: {type(e).__name__}: {e}")


def main():
    args = parse_args()
    rclpy.init()
    node = RealRobotBridge(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.arm.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
