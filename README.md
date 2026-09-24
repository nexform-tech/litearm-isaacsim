# litearm 真机 + Isaac Sim 仿真同步联调

三节点单向数据流：手动指定 SDK API → 真机执行 → 仿真跟随真机实时关节角。

```text
┌──────────────────────────────────────────────────────────────┐
│  publish_api.py  (节点1 · API指令发布器)                       │
│  不连真机、不依赖 SDK；把要执行的 API + 参数打包成 JSON 发布     │
└──────────────────────────────┬───────────────────────────────┘
                               │  std_msgs/String
                               │  /litearm/api_cmd
                               │  {"api": "movej", "args": {...}}
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  real_robot_bridge.py  (节点2 · 真机桥接)                      │
│  订阅指令 → 反射调 arm.<api>(**args) 驱动真机                   │
│  同时周期读 arm.get_state()["q"] → 发布实时关节角               │
└──────────────────────────────┬───────────────────────────────┘
                               │  sensor_msgs/JointState
                               │  /litearm/joint_state
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  isaac_sim_node.py  (节点3 · 仿真节点)                          │
│  订阅实时关节角 → 逐帧写入 USD 关节 (真机怎么动、仿真怎么动)     │
└──────────────────────────────────────────────────────────────┘
```

核心思想：仿真跟随的是「真机实际在哪」，而不是「规划了什么轨迹」。
因此无论动作由哪个 SDK API（movej/movel/movec/力控/零重力拖拽…）产生，
真机一动、状态广播关节角一变，仿真就跟着动。

## 文件清单

| 文件 | 说明 |
|------|------|
| `publish_api.py` | 节点1：手动指定 API，打包 JSON 指令发布（不连真机） |
| `real_robot_bridge.py` | 节点2：订阅指令反射调 SDK 驱动真机，发布实时关节角 |
| `isaac_sim_node.py` | 节点3：订阅实时关节角，驱动 USD 关节 |
| `bridge.launch.py` | 启动节点2 的 ROS2 launch（IP 用 `ip:=` 传参，默认 139） |
| `start_all.sh` | 一键启动节点3（后台）+ 节点2（前台） |
| `run_sim.sh` | 启动仿真节点（节点3）的脚本（含 Isaac Sim 环境设置） |
| `README.md` | 本文件 |

## 依赖

### 1. 真机侧（节点1 + 节点2）

- Python 3 + `litearm-python`（SDK，见 `/home/qql/litearm-python`）
- ROS2 Humble（`std_msgs`、`sensor_msgs`、`rclpy`）
- 工控机 `litearm-server` 已启动，默认 endpoint `tcp/192.168.31.139:7447`

```bash
cd /home/qql/litearm-python
source .venv/bin/activate          # 激活 litearm-python 虚拟环境
source /opt/ros/humble/setup.zsh   # 激活 ROS2
```

### 2. 仿真侧（节点3）

- Isaac Sim 5.x（本机路径 `/home/qql/nvidia/isaac-sim`）
- 干净 USD：`/home/qql/litearm_isaacsim_import/litearm_clean.usd`
  （关节名大写 `Joint1`~`Joint7`）
- ROS2 bridge 扩展（`isaacsim.ros2.bridge`，内部 rclpy）

## 运行步骤

⚠️ **先启动节点2（真机桥接）和节点3（仿真），最后再敲节点1指令**，
否则节点1 等不到订阅者会超时。

### 一键启动（推荐）

`start_all.sh` 自动先起节点3（Isaac Sim，后台）再起节点2（真机桥接，前台），
IP 作为第一个参数传入（默认 192.168.31.139）：

```bash
cd /home/qql/sl/litearm_sync_release
./start_all.sh                # 默认 IP 192.168.31.139
./start_all.sh 192.168.31.139  # 指定 IP
```

Ctrl+C 退出节点2 时会同时清理后台的节点3。

命令节点需自己启动

```bash
cd /home/qql/litearm-python
source .venv/bin/activate && source /opt/ros/humble/setup.zsh

```

### 分开启动（三个终端，调试用）

#### 终端 1 · 节点2 真机桥接（⚠️ 会真实运动）

```bash
cd /home/qql/litearm-python
source .venv/bin/activate && source /opt/ros/humble/setup.zsh
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py \
  --endpoint tcp/192.168.31.139:7447
```

或用 launch 启动（endpoint 的 IP 用 `ip:=` 传参，默认 139）：

```bash
cd /home/qql/litearm-python
source .venv/bin/activate && source /opt/ros/humble/setup.zsh
ros2 launch /home/qql/sl/litearm_sync_release/bridge.launch.py ip:=192.168.31.139
```

#### 终端 2 · 节点3 仿真

```bash
cd /home/qql/sl/litearm_sync_release
./run_sim.sh
```

#### 终端 3 · 节点1 发布 API 指令（手动指定，每次一条）

```bash
cd /home/qql/litearm-python
source .venv/bin/activate && source /opt/ros/humble/setup.zsh

# 关节空间运动（speed 建议先 0.1 低速验证）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api movej --args '{"q_target":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'

# 笛卡尔直线（pose_goal = [位置3], [旋转3x3]）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api movel --args '{"pose_goal":[[0.4,-0.2,0.3],[[1,0,0],[0,1,0],[0,0,1]]],"speed":0.1}'

# 纯计算 fk（不动电机，结果看节点2日志）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api fk --args '{"q":[0,0,0,0,0,0,0]}'

# 零重力（⚠️ 臂会瘫软，人须扶住；务必带 duration_s 自动退出，否则会占死 server 读循环）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api zero_gravity --args '{"duration_s":10}'

# 急停
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api request_stop --args '{}'
```

## 节点1 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--api` | 必填 | 要执行的 SDK API 名（movej/movel/fk/zero_gravity/request_stop …） |
| `--args` | `{}` | API 的 kwargs，JSON 字典字符串 |
| `--topic` | `/litearm/api_cmd` | 发布指令的 topic |

支持的 API 即 `litearm.Arm` 的全部方法（见 `arm.py`），常见的有：

- 运动：`movej`、`movel`、`movec`、`movep`
- 回放：`replay_joint_path`、`replay_trajectory`、`replay_timed_trajectory`、`play_trajectory`
- 规划（纯计算）：`plan_movel`、`plan_movec`、`plan_movep`、`fk`、`ik`
- 录制：`record_trajectory`
- 力控/阻抗：`hold`、`zero_gravity`、`joint_impedance`、`cartesian_impedance`、`joint_follow`
- 安全：`request_stop`、`clear_stop`、`clear_faults`
- 调参：`set_gains`、`get_gains`

## 关键实现要点

1. **统一 JSON 指令**：节点1 用 `std_msgs/String` 发 `{"api", "args"}`，
   避免自定义消息在 Isaac Sim internal rclpy 里的编译加载坑。
2. **反射调用**：节点2 `getattr(arm, api)(**kwargs)`，一套代码覆盖全部 API。
3. **执行线程隔离**：运动类 API 会阻塞到完成，节点2 在独立线程执行，
   不占用 spin 线程，保证状态发布 timer 不停、仿真持续跟随。
4. **实时状态跟随**：仿真订阅 `/litearm/joint_state`（真机实际关节角），
   优先写入；保留轨迹订阅（旧模式）作为降级。
5. **仿真驱动单位是「度」**：USD 关节 `targetPosition` 单位是度不是弧度，
   仿真节点里用 `math.degrees()` 转换。
6. **ROS2 回调不写 USD**：仿真节点回调只存最新关节角，主循环写 DriveAPI，
   避免死锁。

## 安全提示

- ⚠️ 真机会真实运动！运行前确认机械臂上电、工作区无人、急停在手边。
- 首次建议 `--args` 里 `"speed":0.1` 低速验证，确认无异常后再提速。
- 力控/零重力类 API 会让臂瘫软，务必有人扶住机械臂再执行。
