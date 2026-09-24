#!/bin/bash
# 启动 litearm 仿真节点（Isaac Sim + ROS2 订阅）
cd /home/qql/nvidia/isaac-sim
source ./setup_python_env.sh
source ./setup_ros_env.sh
export LD_LIBRARY_PATH="$PWD/exts/isaacsim.ros2.bridge/humble/lib:$LD_LIBRARY_PATH"
export LD_PRELOAD=$PWD/kit/libcarb.so
export CARB_APP_PATH=$PWD/kit
export ISAAC_PATH=$PWD
export EXP_PATH=$PWD/apps
exec ./kit/python/bin/python3 /home/qql/sl/litearm_sync_release/isaac_sim_node.py \
  --/renderer/multiGpu/enabled=false
