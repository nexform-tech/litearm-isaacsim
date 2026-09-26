#!/bin/bash
# 一键启动：节点3（Isaac Sim 仿真）+ 节点2（真机桥接）。
# 节点1（publish_api.py）保持手敲，不在本脚本内。
#
# 真机经 STM32 USB CDC 直连（litearm-python-gitee 薄协议 SDK），无需 server/IP。
#
# 用法（在 litearm_sync_release 目录下）：
#   ./start_all.sh                       # 自动发现 CDC（1d50:606f）
#   ./start_all.sh /dev/ttyACM0          # 指定串口
set -e

PORT="${1:-}"

# ── 1. 让新 SDK 可 import + ROS2 Humble（节点2 需要）──
# 新 SDK 仅依赖 pyserial，系统 python3 已具备；用 PYTHONPATH 指向它的 src 即可。
export PYTHONPATH="/home/qql/sl/litearm-python-gitee/src${PYTHONPATH:+:$PYTHONPATH}"
source /opt/ros/humble/setup.bash

# ── 2. 后台启动节点3（Isaac Sim，最慢，先起）──
echo "[start_all] 后台启动节点3（Isaac Sim 仿真）..."
./run_sim.sh &
SIM_PID=$!

# 给 Isaac Sim 一点时间加载（它内部还要预热几十帧）
echo "[start_all] 等待 Isaac Sim 加载...（约 20s，可提前 Ctrl+C 取消）"
sleep 20

# ── 3. 前台启动节点2（真机桥接，Ctrl+C 退出会同时带走后台节点3）──
if [ -n "${PORT}" ]; then
    echo "[start_all] 启动节点2（真机桥接 port=${PORT}）..."
else
    echo "[start_all] 启动节点2（真机桥接，自动发现 CDC）..."
fi
ros2 launch bridge.launch.py port:=${PORT}

# 节点2 退出后，清理后台的节点3
kill ${SIM_PID} 2>/dev/null || true
echo "[start_all] 已退出"
