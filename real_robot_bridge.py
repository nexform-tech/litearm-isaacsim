#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机桥接节点（节点 2）：订阅 API 指令 → 反射调 SDK 驱动真机；持续发布实时关节角。

三节点单向数据流：
  publish_api.py  ──{api, args}──▶  real_robot_bridge.py  ──实时关节角──▶  isaac_sim_node.py
  （只发指令）                      （反射调 SDK → 真机；发状态）          （订阅状态 → 驱动 USD）

SDK：litearm-python-gitee（LiteArm STM32 直连薄协议后端，仅依赖 pyserial）。
  不连 litearm-server、不需要 IP —— 直连 USB CDC（自动发现 VID:PID 1d50:606f，
  或用 --port / 环境变量 LITEARM_PORT 指定串口）。运动学/规划/动力学都在固件里。

职责：
  1. 连接串口并校验固件版本约定（Litearm<主.次.修>-{7J|1J}，须 ≥1.5.0）。
  2. 连接后【自动 enable()】（可用 --no-enable 跳过，只读联调）。
  3. 订阅 /litearm/api_cmd（std_msgs/String，JSON: {"api": ..., "args": {...}}），
     反射调用 arm.<api>(**args) 驱动真机。指令在独立线程执行，因为运动类 API
     （movej/move_p/move_l/move_c/move_path/home）会阻塞到到位，不能占用 spin 线程。
  4. 周期读取 arm.get_state().value.q（固件 100Hz 状态流的最近一帧，读缓存不发报文），
     发布到 /litearm/joint_state（sensor_msgs/JointState），
     仿真节点订阅后逐帧驱动 USD 关节。无论动作由哪个 API 产生，仿真都跟随。

⚠️ 真机会真实运动！启动即自动使能；力控/零重力等会让臂瘫软，人须扶住。

运行（系统 python3 + ROS2 Humble + 新 SDK 的 src 在 PYTHONPATH 里）：
  export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
  source /opt/ros/humble/setup.zsh
  python3 real_robot_bridge.py                      # 自动发现 CDC
  python3 real_robot_bridge.py --port /dev/ttyACM0  # 指定串口
  python3 real_robot_bridge.py --no-enable           # 只读联调（不使能）
"""
import argparse
import json
import os
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
    ap.add_argument("--port", default=None,
                    help="STM32 CDC 串口，如 /dev/ttyACM0；缺省用环境变量 LITEARM_PORT，再缺省自动发现")
    ap.add_argument("--no-enable", action="store_true",
                    help="连接后不自动 enable（只读联调，运动指令会被固件拒绝）")
    ap.add_argument("--cmd-topic", default="/litearm/api_cmd",
                    help="订阅 API 指令的 topic")
    ap.add_argument("--state-topic", default="/litearm/joint_state",
                    help="发布真机实时关节状态的 topic")
    ap.add_argument("--rate", type=float, default=50.0,
                    help="状态发布频率 Hz（读缓存，默认 50）")
    return ap.parse_args()


class RealRobotBridge(Node):
    def __init__(self, args):
        super().__init__("litearm_real_robot_bridge")

        port = args.port or os.environ.get("LITEARM_PORT") or litearm.find_cdc_port()
        self.arm = litearm.Arm(port=port).connect()
        self.get_logger().info(
            f"[SDK] 已连接 port={port} firmware={self.arm.firmware!r} N={self.arm.n}")

        # 自动使能；失败（如未激活）只告警不退出，仍可发 license/activate/reset 诊断
        if not args.no_enable:
            try:
                self.arm.enable()
                self.get_logger().info("[SDK] 已 enable")
            except Exception as e:
                self.get_logger().error(
                    f"[SDK] enable 失败（可发 --api license / activate 诊断）: "
                    f"{type(e).__name__}: {e}")
        else:
            self.get_logger().warn("[SDK] --no-enable：未使能，运动指令会被固件拒绝")

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
        try:
            st = self.arm.get_state().value   # 2.0 起读一帧的 getter 返回 Msg 信封
        except Exception as e:
            self.get_logger().error(f"[STATE] 读取状态失败: {type(e).__name__}: {e}",
                                    throttle_duration_sec=2.0)
            return
        if st is None or not st.q:
            return
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = [float(x) for x in st.q[:7]]
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
        # 只放行公开可调用成员（挡住 _port/_tr 之类的内部属性）
        if (not isinstance(api, str) or not api or api.startswith("_")
                or not callable(getattr(self.arm, api, None))):
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
