# litearm 真机 + Isaac Sim 仿真同步联调

三节点单向数据流：手动指定 SDK API → 真机执行 → 仿真跟随真机实时关节角。

```
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
│  同时周期读 arm.get_state().value.q → 发布实时关节角            │
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
因此无论动作由哪个 SDK API（movej/move_p/move_l/零重力拖拽…）产生，
真机一动、状态广播关节角一变，仿真就跟着动。

## SDK

真机侧用 **`litearm-python-gitee`**（`/home/qql/sl/litearm-python-gitee`）——
LiteArm **STM32 直连薄协议后端**：经 USB CDC 直接连 `litearm-stm32` 固件，
**无 server、无 IP**。运动学 / 笛卡尔规划 / 动力学 / 控制律都在固件里，
PC 侧只是薄封装（仅依赖 `pyserial`）。

- CDC 自动发现（VID:PID `1d50:606f`），可用 `--port` 或环境变量 `LITEARM_PORT` 指定串口。
- `connect()` 会校验固件版本约定 `Litearm<主.次.修>-{7J|1J}`（须 ≥1.5.0）。
- **运动前必须先 `enable()`**（旧 server 模式不用）。节点2 连接后会自动 `enable()`；
  未激活的板子 `enable()` 会被拒（`ERR{0x10,0x08}`），此时用 `license` / `activate` 诊断。
- 读一帧的 getter（`get_state` / `get_tcp` / …）返回 `Msg` 信封，取值为 `.value`。

## 文件清单

| 文件 | 说明 |
|------|------|
| `publish_api.py` | 节点1：手动指定 API，打包 JSON 指令发布（不连真机） |
| `real_robot_bridge.py` | 节点2：订阅指令反射调 SDK 驱动真机，发布实时关节角 |
| `isaac_sim_node.py` | 节点3：订阅实时关节角，驱动 USD 关节 |
| `bridge.launch.py` | 启动节点2 的 ROS2 launch（串口用 `port:=` 传参，留空=自动发现） |
| `start_all.sh` | 一键启动节点3（后台）+ 节点2（前台） |
| `run_sim.sh` | 启动仿真节点（节点3）的脚本（含 Isaac Sim 环境设置） |
| `README.md` | 英文版说明 |
| `readme_zn.md` | 本文件（中文版） |

## 依赖

### 1. 真机侧（节点1 + 节点2）

- Python 3 + `litearm-python-gitee`（STM32 直连 SDK，源码在 `/home/qql/sl/litearm-python-gitee`，
  用 `PYTHONPATH` 指向它的 `src` 即可，无需 pip 安装）
- `pyserial`（系统 `python3` 已具备）
- ROS2 Humble（`std_msgs`、`sensor_msgs`、`rclpy`）
- 机械臂经 STM32 USB CDC 直连本机（无需工控机 / 无线）

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh   # 或 setup.bash
```

### 2. 仿真侧（节点3）

- Isaac Sim 5.x（本机路径 `/home/qql/nvidia/isaac-sim`）
- 干净 USD：`/home/qql/litearm_isaacsim_import/litearm_clean.usd`
  （关节名大写 `Joint1`~`Joint7`）
- ROS2 bridge 扩展（`isaacsim.ros2.bridge`，内部 rclpy）

### 3. 路径覆盖

上面所有硬编码路径都有环境变量覆盖，旧值仍是默认值，因此同一套脚本在
devcontainer 和路径不同的机器上都能原样运行：

| 变量 | 使用方 | 默认值 |
|----------|---------|---------|
| `ISAAC_SIM_DIR` | 节点3 | `/home/qql/nvidia/isaac-sim` |
| `LITEARM_USD` | 节点3 | `/home/qql/litearm_isaacsim_import/litearm_clean.usd` |
| `LITEARM_SIM_LOG` | 节点3 | `/home/qql/sim_node_log.txt` |
| `LITEARM_HEADLESS` | 节点3 | 不设置（显示窗口）；设为 `1` 时无头运行 |
| `LITEARM_SDK_SRC` | 节点2 | `/home/qql/sl/litearm-python-gitee/src` |
| `ROS_SETUP_BASH` | 节点2 | `/opt/ros/humble/setup.bash` |

## 运行步骤

⚠️ **先启动节点2（真机桥接）和节点3（仿真），最后再敲节点1指令**，
否则节点1 等不到订阅者会超时。

### 一键启动（推荐）

`start_all.sh` 自动先起节点3（Isaac Sim，后台）再起节点2（真机桥接，前台），
串口作为第一个参数传入（默认留空 = 自动发现）：

```bash
cd /home/qql/sl/litearm_sync_release
./start_all.sh                     # 自动发现 CDC
./start_all.sh /dev/ttyACM0        # 指定串口
```

Ctrl+C 退出节点2 时会同时清理后台的节点3。

命令节点需自己启动
```bash
cd /home/qql/sl/litearm_sync_release
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
```

### 分开启动（三个终端，调试用）

#### 终端 1 · 节点2 真机桥接（⚠️ 会真实运动）

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py            # 自动发现 CDC
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py --port /dev/ttyACM0
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py --no-enable  # 只读联调（不使能）
```

或用 launch 启动（串口用 `port:=` 传参，留空=自动发现）：

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
ros2 launch /home/qql/sl/litearm_sync_release/bridge.launch.py port:=/dev/ttyACM0
```

#### 终端 2 · 节点3 仿真

```bash
cd /home/qql/sl/litearm_sync_release
./run_sim.sh
```

#### 终端 3 · 节点1 发布 API 指令（手动指定，每次一条）

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh

# 关节空间运动（q 为目标关节角，speed 建议先 0.1 低速验证）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api movej --args '{"q":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'

# 笛卡尔直线（pose = 位置3 + rpy3，或 + 3x3旋转矩阵）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api move_l --args '{"pose":[0.30,0,0.35,3.1416,0,0],"speed":0.1}'

# 固件异步 IK：pose -> 关节角（不动电机，结果看节点2日志）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api ik --args '{"pose":[0.30,0,0.35,3.1416,0,0]}'

# 读当前末端位姿（只读）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api get_tcp --args '{}'

# 零重力（⚠️ 臂会瘫软，人须扶住；进入后须显式退出）
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api zero_g --args '{}'
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api zero_g_stop --args '{}'

# 急停
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api emergency_stop --args '{}'
```

## 在 devcontainer 中开发

本节面向想在 VS Code 里直接获得完整 Isaac Sim + ROS 2 环境、而不在宿主机上
安装两者的开发者。仓库自带 devcontainer 定义，基于 NVIDIA 官方 Isaac Sim
Docker 镜像构建，在容器中打开文件夹即可运行全部三个节点。

### 1. 前置条件

- 支持 GPU 的 Docker：Linux 上用 Docker Engine +
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，
  Windows 上用 WSL2 后端的 Docker Desktop。
- NVIDIA 驱动 570.169 或更新（Isaac Sim 5.1.0 镜像的最低要求），用
  `nvidia-smi` 检查。
- VS Code + [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
  扩展。
- 能访问 `nvcr.io` 拉取 Isaac Sim 镜像。该镜像拉取无需 NGC 登录（已通过
  `nvcr.io` registry API 验证）。

### 2. 在容器中打开仓库

1. 克隆仓库并用 VS Code 打开。
2. 按 F1 运行 **Dev Containers: Reopen in Container**（VS Code 检测到
   `.devcontainer` 目录时也会自动提示）。首次构建要拉取 Isaac Sim 镜像并
   安装 ROS 2 Jazzy，比较耗时；之后重建会快很多。

镜像基于 Ubuntu 24.04，因此容器里节点1、节点2 用 ROS 2 **Jazzy**，节点3
仍用 Isaac Sim 自带 ROS2 bridge 扩展里的 Humble rclpy；两侧走默认的
Fast DDS RMW 通信，跨发行版线缆协议兼容（未验证：本文撰写时未在这台机器上
执行过容器构建）。

### 3. 提供 SDK 与 USD 场景（一次性）

容器需要两个不在仓库里的输入，都放在 Docker volume 里以便重建后仍然存在：

- `/opt/litearm-python-gitee` — `litearm-python-gitee` SDK 源码
  （`litearm-sdk` volume）。
- `/opt/litearm-assets/litearm_clean.usd` — 干净 USD 场景
  （`litearm-assets` volume）。

打开容器前在宿主机上设置 Gitee 地址，然后重建，即可自动克隆 SDK：

```powershell
$env:LITEARM_SDK_GIT_URL = "https://gitee.com/<你的组织>/litearm-python-gitee.git"
```

也可以在容器内终端里克隆一次；volume 在重建后依然保留：

```bash
git clone https://gitee.com/<你的组织>/litearm-python-gitee.git /opt/litearm-python-gitee
```

在宿主机上把 USD 场景复制进 assets volume（在仓库目录下执行）：

```bash
docker run --rm -v litearm-assets:/assets -v "$PWD":/host alpine \
    cp /host/litearm_clean.usd /assets/litearm_clean.usd
```

### 4. 运行节点

容器终端里的命令和裸机一致，所有路径都由 devcontainer 环境设好：

```bash
cd /workspaces/litearm-isaacsim
./run_sim.sh        # 节点3：仿真
./start_all.sh      # 节点3（后台）+ 节点2（真机桥接）
python3 publish_api.py --api movej --args '{"q":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'
```

驱动真机前请先读[运行步骤](#运行步骤)和[安全提示](#安全提示)。

### 5. GUI、无头模式与平台限制

- **Linux 宿主机 GUI：**devcontainer 已挂载 X11 socket 并透传 `DISPLAY`，
  宿主机上先执行 `xhost +local:`。Windows 上安装 VcXsrv 等 X server 并允许
  容器连接。
- **无头模式：**`LITEARM_HEADLESS=1 ./run_sim.sh` 即可无窗口启动仿真。
- **浏览器推流：**Isaac Sim 的 WebRTC 推流需要 host 网络，devcontainer
  默认不用 host 网络。不要指望转发的 49100/47998 端口能传视频流；Linux
  宿主机可在 `.devcontainer/devcontainer.json` 的 `runArgs` 里加
  `"--network=host"`，再以推流模式启动容器。
- **真机（节点2）：**USB 透传只在 Linux 宿主机上可用。Windows 和 macOS 的
  Docker Desktop 无法把 USB 设备传进容器，因此节点2 在这类机器上连不到
  真机；节点1、节点3 不受影响。
- **Isaac Sim 版本：**devcontainer 默认构建
  `nvcr.io/nvidia/isaac-sim:5.1.0`。改 `.devcontainer/devcontainer.json`
  里的 `ISAAC_SIM_TAG` 即可换版本。

## 节点1 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--api` | 必填 | 要执行的 SDK API 名（见下） |
| `--args` | `{}` | API 的 kwargs，JSON 字典字符串（形参名即 SDK 形参名） |
| `--topic` | `/litearm/api_cmd` | 发布指令的 topic |

节点2 的 `real_robot_bridge.py` 参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--port` | 自动发现 | STM32 CDC 串口；缺省用 `LITEARM_PORT`，再缺省自动发现 `1d50:606f` |
| `--no-enable` | 关 | 连接后不自动 `enable()`（只读联调） |
| `--cmd-topic` | `/litearm/api_cmd` | 订阅指令的 topic |
| `--state-topic` | `/litearm/joint_state` | 发布实时关节状态的 topic |
| `--rate` | `50` | 状态发布频率 Hz |

支持的 API 即 `litearm.Arm`（新 SDK）的公开方法，常见的有：

- 连接/使能：`connect`、`reconnect`、`close`、`enable`、`disable`
- 运动：`movej`、`movej_sync`、`move_p`（关节空间 PTP）、`home`
- 笛卡尔（固件规划）：`move_l`（直线）、`move_c`（圆弧，起点须为实测 TCP）、`move_path`（多路点）
- 查询/计算：`get_state`、`get_status_now`、`get_tcp`、`ik`
- 安全：`emergency_stop`、`reset`、`clear_faults`
- 零重力：`zero_g`（进入 + 后台保活）、`zero_g_stop`（退出）
- 连续伺服/透传：`move_js`、`send_mit`、`send_mit_all`
- 调参：`set_speed`、`park`、`set_motion_mode`、`set_*` / `get_*`（动力学与控制律）
- 授权：`license`、`activate`

> 反射只到顶层可调用方法，`arm.params.*` / `arm.log.*` / `arm.diag.*` 等子命名空间
> 不经节点1（要用直接写脚本调 SDK）。

⚠️ 新 SDK **没有** `movel`/`movec`/`fk`/`hold`/`joint_impedance` 等
（PC 侧不做规划/力控；FK 只有当前反馈 `get_tcp()`，没有任意关节角 `fk(q)`）。
高级力控场景仍走 `pylitearm` + server。

## 关键实现要点

1. **统一 JSON 指令**：节点1 用 `std_msgs/String` 发 `{"api", "args"}`，
   避免自定义消息在 Isaac Sim internal rclpy 里的编译加载坑。
2. **反射调用**：节点2 `getattr(arm, api)(**kwargs)`，一套代码覆盖全部 API；
   只放行公开可调用成员（挡 `_` 开头的内部属性）。
3. **执行线程隔离**：运动类 API 会阻塞到到位，节点2 在独立线程执行，
   不占用 spin 线程，保证状态发布 timer 不停、仿真持续跟随。
4. **自动使能**：新 SDK 运动前必须先 `enable()`，节点2 连接后自动使能；
   失败只告警不退出，便于诊断。
5. **实时状态跟随**：仿真订阅 `/litearm/joint_state`（真机实际关节角），
   优先写入；保留轨迹订阅（旧模式）作为降级。状态读取用 `get_state().value`
   （`Msg` 信封；读的是固件 100Hz 状态流缓存，不逐次发报文）。
6. **仿真驱动单位是「度」**：USD 关节 `targetPosition` 单位是度不是弧度，
   仿真节点里用 `math.degrees()` 转换。
7. **ROS2 回调不写 USD**：仿真节点回调只存最新关节角，主循环写 DriveAPI，
   避免死锁。

## 安全提示

- ⚠️ 真机会真实运动！运行前确认机械臂上电、工作区无人、急停在手边。
- 节点2 启动即自动使能（机械臂上力）；只做联调可加 `--no-enable`。
- 首次建议 `--args` 里 `"speed":0.1` 低速验证，确认无异常后再提速。
- 零重力/力控类会让臂瘫软，务必有人扶住机械臂再执行；`zero_g` 进入后须 `zero_g_stop` 退出。
