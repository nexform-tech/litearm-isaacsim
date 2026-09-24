#!/bin/bash
# 一键启动：节点3（Isaac Sim 仿真）+ 节点2（真机桥接）。
# 节点1（publish_api.py）保持手敲，不在本脚本内。
#
# 用法（在 litearm_sync_release 目录下）：
#   ./start_all.sh [ip]
#   ./start_all.sh 192.168.31.139
set -e

IP="${1:-192.168.31.139}"

# ── 1. 激活 litearm-python venv + ROS2 Humble（节点2 需要）──
source /home/qql/litearm-python/.venv/bin/activate
source /opt/ros/humble/setup.zsh 2>/dev/null || source /opt/ros/humble/setup.bash

# ── 2. 后台启动节点3（Isaac Sim，最慢，先起）──
echo "[start_all] 后台启动节点3（Isaac Sim 仿真）..."
./run_sim.sh &
SIM_PID=$!

# 给 Isaac Sim 一点时间加载（它内部还要预热几十帧）
echo "[start_all] 等待 Isaac Sim 加载...（约 20s，可提前 Ctrl+C 取消）"
sleep 20

# ── 3. 前台启动节点2（真机桥接，Ctrl+C 退出会同时带走后台节点3）──
echo "[start_all] 启动节点2（真机桥接 endpoint=tcp/${IP}:7447）..."
ros2 launch bridge.launch.py ip:=${IP}

# 节点2 退出后，清理后台的节点3
kill ${SIM_PID} 2>/dev/null || true
echo "[start_all] 已退出"
