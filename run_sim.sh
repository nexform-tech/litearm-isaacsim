#!/bin/bash
# 启动 litearm 仿真节点（Isaac Sim + ROS2 订阅）
# Isaac Sim 安装目录可用 ISAAC_SIM_DIR 覆盖（容器内为 /isaac-sim）
ISAAC_SIM_DIR="${ISAAC_SIM_DIR:-/home/qql/nvidia/isaac-sim}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ISAAC_SIM_DIR"
source ./setup_python_env.sh
source ./setup_ros_env.sh
export LD_LIBRARY_PATH="$PWD/exts/isaacsim.ros2.bridge/humble/lib:$LD_LIBRARY_PATH"
export LD_PRELOAD=$PWD/kit/libcarb.so
export CARB_APP_PATH=$PWD/kit
export ISAAC_PATH=$PWD
export EXP_PATH=$PWD/apps
exec ./kit/python/bin/python3 "$SCRIPT_DIR/isaac_sim_node.py" \
  --/renderer/multiGpu/enabled=false
