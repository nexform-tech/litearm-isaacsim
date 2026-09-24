#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isaac Sim 仿真节点：订阅 ROS2 /litearm/joint_target 驱动 USD 关节。

运行方式（不要 source 系统 Humble，用 bash 设 internal rclpy 路径；绕开 python.sh 的 $args bug）：
  cd /home/qql/nvidia/isaac-sim
  bash -c 'source ./setup_python_env.sh && source ./setup_ros_env.sh && \
    export LD_LIBRARY_PATH="$PWD/exts/isaacsim.ros2.bridge/humble/lib:$LD_LIBRARY_PATH" && \
    export LD_PRELOAD=$PWD/kit/libcarb.so && \
    export CARB_APP_PATH=$PWD/kit ISAAC_PATH=$PWD EXP_PATH=$PWD/apps && \
    ./kit/python/bin/python3 /home/qql/sl/litearm_sync/isaac_sim_node.py'
"""
import threading
import sys
import os
import math
import time as _time

LOG = "/home/qql/sim_node_log.txt"
USD_PATH = "/home/qql/litearm_isaacsim_import/litearm_clean.usd"


def log(msg):
    line = "[sim] " + msg
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


log("脚本开始执行")

from isaacsim import SimulationApp

# headless=False 显示 GUI，能直接看到机械臂动。
# 降采样减负，避免 8GB 显存在 realtime 内核下被打满导致死机。
# 注意：不要手动指定 renderer，交给 Isaac Sim 默认 RTX 渲染器（会自动处理光照）
# 关键：混合显卡（Intel 核显 + NVIDIA 独显）机器上必须关掉 multiGpu，
#       否则渲染 graph 状态不一致，USD reopen 时段错误崩溃
simulation_app = SimulationApp({
    "headless": False,
    "width": 1280,
    "height": 720,
    "anti_aliasing": "FXAA",
    "/renderer/multiGpu/enabled": False,
})

import omni
import omni.timeline
from pxr import UsdPhysics, Usd

log("SimulationApp 创建完成")

# ── 1. 注入 internal rclpy 路径（必须先于 enable_extension，否则报 no attribute 'impl'）──
BRIDGE_RCLPY = "/home/qql/nvidia/isaac-sim/exts/isaacsim.ros2.bridge/humble/rclpy"
if os.path.isdir(BRIDGE_RCLPY):
    sys.path.insert(0, BRIDGE_RCLPY)
    log("已注入 internal rclpy 路径")

try:
    from isaacsim.core.utils import extensions
    extensions.enable_extension("isaacsim.ros2.bridge")
    log("已启用 isaacsim.ros2.bridge 扩展")
except Exception as e:
    log(f"启用 bridge 扩展失败: {type(e).__name__}: {e}")

# ── 1.5 关键：bridge 扩展是异步启动的，会在后续 update() 里才真正 load rclpy。
#     若此时 stage 已有带 reference 的网格，load 过程触发 reopenUsd 段错误。
#     所以在打开 USD 之前，先在【空 stage】上跑若干帧，让 bridge 彻底启动完成。
log("空 stage 预热，等待 bridge 扩展启动完成（异步 load rclpy）")
for _ in range(30):
    simulation_app.update()
log("bridge 扩展预热完成")

# ── 2. import rclpy ──
RCLPY_OK = False
try:
    import rclpy
    from rclpy.node import Node
    from trajectory_msgs.msg import JointTrajectory
    from sensor_msgs.msg import JointState
    log("rclpy import OK")
    RCLPY_OK = True
except Exception as e:
    log(f"rclpy import 失败: {type(e).__name__}: {e}")


# ── 3. 打开 USD 场景（已含关节 + ArticulationRoot + Drive，无需再导入 URDF）──
def open_usd():
    ctx = omni.usd.get_context()
    ctx.new_stage()
    ok = ctx.open_stage(USD_PATH)
    stage = ctx.get_stage()
    # 关键：分层 USD 的网格在 payload 里，懒加载。必须显式 load 所有 payload，
    # 否则网格 0 个，reopenUsd 处理空结构时段错误崩溃
    from pxr import Usd
    for prim in stage.TraverseAll():
        if prim.HasPayload():
            prim.Load()
    log(f"打开 USD ok={ok}: {USD_PATH}")
    return stage


def setup_articulation(stage):
    """找到 7 个 revolute 关节，返回关节 prim 列表（USD 已自带 ArticulationRoot）。"""
    joints = []
    for prim in stage.TraverseAll():
        if prim.GetTypeName() == "PhysicsRevoluteJoint":
            joints.append(prim)
    # 按关节名排序，确保顺序稳定
    joints.sort(key=lambda p: p.GetName())
    log(f"找到 {len(joints)} 个 revolute 关节: {[p.GetName() for p in joints]}")
    return joints


# ── 4. 仿真节点类（订阅轨迹 topic，按时间轴跟随驱动关节）──
# 关键：ROS2 回调在 spin 线程执行，不能直接写 USD（会死锁）。
# 回调只把轨迹存进变量，主循环里按时间轴逐帧跟随驱动。
class SimNode(Node):
    def __init__(self, topic, state_topic, joints):
        super().__init__("litearm_sim")
        self.joints = joints
        self.lock = threading.Lock()
        self.traj_q = []            # N×7 关节角（弧度）
        self.traj_t = []            # N 个时间戳（秒）
        self.traj_start = None      # 收到轨迹的墙钟时间，用于推进
        self.q_live = None          # 实时状态最新关节角（弧度），直接跟随
        self.sub = self.create_subscription(JointTrajectory, topic, self._cb, 10)
        log(f"订阅轨迹 {topic}，关节数 {len(joints)}")
        # 实时状态订阅：真机怎么动、仿真怎么动（覆盖任意 SDK API 产生的动作）
        self.state_sub = self.create_subscription(
            JointState, state_topic, self._cb_state, 10)
        log(f"订阅实时状态 {state_topic}，关节数 {len(joints)}")

    def _cb(self, msg: JointTrajectory):
        if len(msg.points) < 2:
            log(f"收到轨迹点数不足 2，忽略")
            return
        traj_q = []
        traj_t = []
        for p in msg.points:
            if len(p.positions) < 7:
                continue
            traj_q.append([float(x) for x in p.positions[:7]])
            traj_t.append(p.time_from_start.sec + p.time_from_start.nanosec * 1e-9)
        with self.lock:
            self.traj_q = traj_q
            self.traj_t = traj_t
            self.traj_start = _time.time()
            self.q_live = None   # 轨迹模式优先，先清掉实时跟随
        log(f"收到轨迹 {len(traj_q)} 点，时长 {traj_t[-1]:.2f}s，开始跟随")

    def _cb_state(self, msg: JointState):
        """实时状态回调：只存最新关节角，主循环里写 USD，避免 spin 线程写 USD 死锁。"""
        if len(msg.position) < 7:
            return
        with self.lock:
            self.q_live = [float(x) for x in msg.position[:7]]

    def drive_pending(self):
        """主循环调用：优先跟随实时状态；无实时状态时按轨迹时间轴推进。"""
        with self.lock:
            q_live = self.q_live
            traj_q = self.traj_q
            traj_t = self.traj_t
            traj_start = self.traj_start
        if q_live is not None:
            self._write(q_live)
            return
        if not traj_q or traj_start is None:
            return
        elapsed = _time.time() - traj_start
        q = self._sample(traj_q, traj_t, elapsed)
        if q is None:
            return
        self._write(q)

    def _sample(self, traj_q, traj_t, t):
        """线性插值取 t 时刻的关节角；超时后停在末点。"""
        if t <= traj_t[0]:
            return traj_q[0]
        if t >= traj_t[-1]:
            return traj_q[-1]
        for i in range(len(traj_t) - 1):
            if traj_t[i] <= t <= traj_t[i + 1]:
                span = traj_t[i + 1] - traj_t[i]
                f = 0.0 if span == 0 else (t - traj_t[i]) / span
                q = []
                for a, b in zip(traj_q[i], traj_q[i + 1]):
                    q.append(a + (b - a) * f)
                return q
        return traj_q[-1]

    def _write(self, q):
        # 关键：UsdPhysics 关节角度属性（targetPosition）单位是「度」，
        # 不是弧度！URDF 的 rad 已被 importer 转成 degree 存进 USD。
        # 所以这里要把弧度转成度再写入，否则角度被当成度、幅度极小。
        for prim, angle in zip(self.joints, q):
            if prim is None:
                continue
            drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
            drive.GetStiffnessAttr().Set(1000000.0)
            drive.GetDampingAttr().Set(10000.0)
            drive.GetTargetPositionAttr().Set(float(math.degrees(angle)))


# ── 5. 主流程 ──
stage = open_usd()

joints = setup_articulation(stage)

# USD 已自带灯光/环境/相机，无需再手动加灯光
log("所有 prim 就绪，准备进入订阅与主循环")

# ── 5.5 预热帧：让 reference 网格完全加载后再 Play。
#     否则 open_stage 后立刻 Play，Fabric 边懒加载网格边物理求解会触发
#     reopenUsd 段错误（这是本机 realtime 内核 + 混合显卡下的已知崩溃）。
log("Play 前预热 60 帧，加载 reference 网格")
for _ in range(60):
    simulation_app.update()
log("预热完成")

# ── 6. ROS2 订阅 + spin 线程 ──
node = None
spin_thread = None
if RCLPY_OK and joints:
    topic = "/litearm/joint_traj"
    state_topic = "/litearm/joint_state"
    rclpy.init()
    log("rclpy.init() 完成")
    node = SimNode(topic, state_topic, joints)
    log(f"已创建 ROS2 订阅，等待 {topic} / {state_topic} 消息...")
    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()
    log("spin 线程已启动")
else:
    log(f"订阅未启动: RCLPY_OK={RCLPY_OK} joints={len(joints)}")

# ── 7. 确保 Play 状态（关节 Drive 生效需要）──
tl = omni.timeline.get_timeline_interface()
if not tl.is_playing():
    tl.play()
    log("已启动 Play 状态")

# ── 8. 主循环 ──
log("进入主循环（按 Ctrl+C 退出）")
try:
    while simulation_app.is_running():
        simulation_app.update()
        if node is not None:
            node.drive_pending()
except KeyboardInterrupt:
    pass

log("脚本退出")
if node is not None:
    rclpy.shutdown()
simulation_app.close()
