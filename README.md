# litearm Real Robot + Isaac Sim Synchronization

Three-node, one-way data flow: specify an SDK API manually → execute on the real robot → the simulation
follows the real robot's joint angles in real time.

```text
┌──────────────────────────────────────────────────────────────┐
│  publish_api.py  (Node 1 · API command publisher)             │
│  No robot connection, no SDK dependency; packages the API      │
│  and its args into a JSON message and publishes it             │
└──────────────────────────────┬───────────────────────────────┘
                               │  std_msgs/String
                               │  /litearm/api_cmd
                               │  {"api": "movej", "args": {...}}
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  real_robot_bridge.py  (Node 2 · real robot bridge)           │
│  Subscribes to commands → reflectively calls arm.<api>(**args) │
│  to drive the robot; also polls arm.get_state().value.q and    │
│  publishes the live joint angles                               │
└──────────────────────────────┬───────────────────────────────┘
                               │  sensor_msgs/JointState
                               │  /litearm/joint_state
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  isaac_sim_node.py  (Node 3 · simulation node)                │
│  Subscribes to live joint angles → writes them into the USD    │
│  joints every frame (as the robot moves, so does the sim)      │
└──────────────────────────────────────────────────────────────┘
```

Core idea: the simulation follows *where the real robot actually is*, not *what trajectory was planned*.
So no matter which SDK API produced the motion (movej / move_p / move_l / zero-g drag, …),
the moment the real robot moves and the broadcast joint angles change, the simulation follows.

## SDK

The robot side uses **`litearm-python-gitee`** (`/home/qql/sl/litearm-python-gitee`) —
a LiteArm **STM32 direct-connection thin-protocol backend**: it talks to the
`litearm-stm32` firmware over USB CDC, with **no server and no IP**. Kinematics,
Cartesian planning, dynamics, and control laws all live in the firmware; the PC side
is a thin wrapper (depending only on `pyserial`).

- CDC auto-discovery (VID:PID `1d50:606f`); use `--port` or the `LITEARM_PORT` env var to specify a serial port.
- `connect()` validates the firmware version string `Litearm<major.minor.patch>-{7J|1J}` (must be ≥1.5.0).
- **`enable()` is mandatory before motion** (not needed in the old server mode). Node 2 calls `enable()` automatically after connecting;
  an unlicensed board rejects `enable()` (`ERR{0x10,0x08}`) — use `license` / `activate` to diagnose in that case.
- Single-frame getters (`get_state` / `get_tcp` / …) return a `Msg` envelope; read the value via `.value`.

## File List

| File | Description |
|------|-------------|
| `publish_api.py` | Node 1: specify an API manually, package it as a JSON command and publish it (no robot connection) |
| `real_robot_bridge.py` | Node 2: subscribe to commands, reflectively call the SDK to drive the robot, publish live joint angles |
| `isaac_sim_node.py` | Node 3: subscribe to live joint angles, drive the USD joints |
| `bridge.launch.py` | ROS2 launch for Node 2 (pass the serial port via `port:=`; leave empty for auto-discovery) |
| `start_all.sh` | One-shot launcher for Node 3 (background) + Node 2 (foreground) |
| `run_sim.sh` | Launcher script for the simulation node (Node 3), including Isaac Sim environment setup |
| `README.md` | This file (English) |
| `readme_zn.md` | Chinese version of this document |

## Dependencies

### 1. Robot side (Node 1 + Node 2)

- Python 3 + `litearm-python-gitee` (STM32 direct SDK; source at `/home/qql/sl/litearm-python-gitee`,
  point `PYTHONPATH` at its `src`, no pip install needed)
- `pyserial` (already available in the system `python3`)
- ROS2 Humble (`std_msgs`, `sensor_msgs`, `rclpy`)
- Robotic arm connected directly to this machine via STM32 USB CDC (no IPC / wireless needed)

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh   # or setup.bash
```

### 2. Simulation side (Node 3)

- Isaac Sim 5.x (local path `/home/qql/nvidia/isaac-sim`)
- Clean USD: `/home/qql/litearm_isaacsim_import/litearm_clean.usd`
  (joint names capitalized `Joint1`–`Joint7`)
- ROS2 bridge extension (`isaacsim.ros2.bridge`, which bundles rclpy)

### 3. Path overrides

Every hardcoded path above has an environment variable override with the old
value as the default, so the same scripts run unchanged in the devcontainer and
on machines whose paths differ:

| Variable | Used by | Default |
|----------|---------|---------|
| `ISAAC_SIM_DIR` | Node 3 | `/home/qql/nvidia/isaac-sim` |
| `LITEARM_USD` | Node 3 | `/home/qql/litearm_isaacsim_import/litearm_clean.usd` |
| `LITEARM_SIM_LOG` | Node 3 | `/home/qql/sim_node_log.txt` |
| `LITEARM_HEADLESS` | Node 3 | unset (window shown); set to `1` for headless |
| `LITEARM_SDK_SRC` | Node 2 | `/home/qql/sl/litearm-python-gitee/src` |
| `ROS_SETUP_BASH` | Node 2 | `/opt/ros/humble/setup.bash` |

## Running

⚠️ **Start Node 2 (real robot bridge) and Node 3 (simulation) first, and only then issue Node 1 commands**,
otherwise Node 1 will time out waiting for subscribers.

### One-shot launch (recommended)

`start_all.sh` starts Node 3 (Isaac Sim, background) and then Node 2 (real robot bridge, foreground).
The serial port is passed as the first argument (empty by default = auto-discovery):

```bash
cd /home/qql/sl/litearm_sync_release
./start_all.sh                     # auto-discover CDC
./start_all.sh /dev/ttyACM0        # explicit serial port
```

Pressing Ctrl+C to exit Node 2 also cleans up the background Node 3.

The command node must be started separately:

```bash
cd /home/qql/sl/litearm_sync_release
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
```

### Separate launch (three terminals, for debugging)

#### Terminal 1 · Node 2 real robot bridge (⚠️ causes real motion)

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py            # auto-discover CDC
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py --port /dev/ttyACM0
python3 /home/qql/sl/litearm_sync_release/real_robot_bridge.py --no-enable  # read-only bring-up (no enable)
```

Or launch it via ROS2 (pass the serial port via `port:=`; empty = auto-discovery):

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh
ros2 launch /home/qql/sl/litearm_sync_release/bridge.launch.py port:=/dev/ttyACM0
```

#### Terminal 2 · Node 3 simulation

```bash
cd /home/qql/sl/litearm_sync_release
./run_sim.sh
```

#### Terminal 3 · Node 1 publishing API commands (manual, one per invocation)

```bash
export PYTHONPATH=/home/qql/sl/litearm-python-gitee/src:$PYTHONPATH
source /opt/ros/humble/setup.zsh

# Joint-space motion (q is the target joint angles; start with speed 0.1 for a low-speed check)
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api movej --args '{"q":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'

# Cartesian straight line (pose = position3 + rpy3, or + 3x3 rotation matrix)
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api move_l --args '{"pose":[0.30,0,0.35,3.1416,0,0],"speed":0.1}'

# Firmware async IK: pose -> joint angles (does not move the motors; check Node 2 logs for the result)
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api ik --args '{"pose":[0.30,0,0.35,3.1416,0,0]}'

# Read the current end-effector pose (read-only)
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api get_tcp --args '{}'

# Zero gravity (⚠️ the arm goes limp — hold it by hand; must be explicitly exited afterwards)
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api zero_g --args '{}'
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api zero_g_stop --args '{}'

# Emergency stop
python3 /home/qql/sl/litearm_sync_release/publish_api.py \
  --api emergency_stop --args '{}'
```

## Develop in a devcontainer

This section is for developers who want the full Isaac Sim + ROS 2 environment
in VS Code without installing either on the host. The repository ships a
devcontainer definition that builds on the official Isaac Sim Docker image, so
opening the folder in a container gives you all three nodes ready to run.

### 1. Prerequisites

- Docker with GPU support: Docker Engine with the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  on Linux, or Docker Desktop with the WSL2 backend on Windows.
- NVIDIA driver 570.169 or newer, the minimum the Isaac Sim 5.1.0 image
  requires. Check with `nvidia-smi`.
- VS Code with the
  [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
  extension.
- Network access to `nvcr.io` to pull the Isaac Sim image. No NGC login is
  required for this image (verified against the `nvcr.io` registry API).

### 2. Open the repository in the container

1. Clone the repository and open it in VS Code.
2. Press F1 and run **Dev Containers: Reopen in Container**. VS Code also
   offers this command automatically when it detects the `.devcontainer`
   folder. The first build pulls the Isaac Sim image and installs ROS 2
   Jazzy, so it takes a while; rebuilds are faster.

The image is Ubuntu 24.04, so Node 1 and Node 2 use ROS 2 Jazzy in the
container, while Node 3 keeps the Humble rclpy bundled inside Isaac Sim's
ROS2 bridge extension. The two sides talk over the default Fast DDS RMW,
which is wire-compatible across distros (unverified: the container build was
not executed on the machine where this was written).

### 3. Provide the SDK and the USD scene (one-time)

The container expects two inputs that are not in this repository, both kept in
Docker volumes so they survive rebuilds:

- `/opt/litearm-python-gitee` — the `litearm-python-gitee` SDK source
  (`litearm-sdk` volume).
- `/opt/litearm-assets/litearm_clean.usd` — the clean USD scene
  (`litearm-assets` volume).

Provide the SDK by setting the Gitee URL on the host before opening the
container, then rebuild:

```powershell
$env:LITEARM_SDK_GIT_URL = "https://gitee.com/<your-org>/litearm-python-gitee.git"
```

Or clone it once from a terminal inside the container; the volume keeps it
across rebuilds:

```bash
git clone https://gitee.com/<your-org>/litearm-python-gitee.git /opt/litearm-python-gitee
```

Copy the USD scene into the assets volume from the host (run this in the
repository directory):

```bash
docker run --rm -v litearm-assets:/assets -v "$PWD":/host alpine \
    cp /host/litearm_clean.usd /assets/litearm_clean.usd
```

### 4. Run the nodes

Inside the container terminal the commands are the same as on bare metal; all
paths are set by the devcontainer environment:

```bash
cd /workspaces/litearm-isaacsim
./run_sim.sh        # Node 3: simulation
./start_all.sh      # Node 3 (background) + Node 2 (real robot)
python3 publish_api.py --api movej --args '{"q":[0,0.6,0,-1.2,0,0.7,0],"speed":0.1}'
```

Read [Running](#running) and [Safety Notes](#safety-notes) before driving the
real robot.

### 5. GUI, headless mode, and platform limits

- **GUI on a Linux host:** the devcontainer mounts the X11 socket and forwards
  `DISPLAY`. Run `xhost +local:` on the host first. On Windows, install an X
  server such as VcXsrv and allow connections from the container.
- **Headless:** run `LITEARM_HEADLESS=1 ./run_sim.sh` to start the simulation
  without a window.
- **Livestream to a browser:** Isaac Sim's WebRTC livestream needs host
  networking, which the devcontainer does not use by default. Do not rely on
  the forwarded ports 49100/47998 for the video stream; on Linux hosts add
  `"--network=host"` to `runArgs` in `.devcontainer/devcontainer.json` and
  start the container in livestream mode.
- **Real robot (Node 2):** USB passthrough works on Linux hosts. Docker
  Desktop on Windows and macOS cannot pass USB devices into containers, so
  Node 2 cannot reach the robot there; Nodes 1 and 3 still work.
- **Isaac Sim version:** the devcontainer builds
  `nvcr.io/nvidia/isaac-sim:5.1.0` by default. Change `ISAAC_SIM_TAG` in
  `.devcontainer/devcontainer.json` to switch versions.

## Node 1 Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--api` | required | Name of the SDK API to execute (see below) |
| `--args` | `{}` | kwargs for the API, as a JSON object string (parameter names match the SDK's) |
| `--topic` | `/litearm/api_cmd` | Topic on which to publish commands |

Arguments for Node 2 `real_robot_bridge.py`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--port` | auto-discover | STM32 CDC serial port; falls back to `LITEARM_PORT`, then to auto-discovery of `1d50:606f` |
| `--no-enable` | off | Do not call `enable()` automatically after connecting (read-only bring-up) |
| `--cmd-topic` | `/litearm/api_cmd` | Topic to subscribe to for commands |
| `--state-topic` | `/litearm/joint_state` | Topic on which to publish live joint state |
| `--rate` | `50` | State publish rate in Hz |

The supported APIs are the public methods of `litearm.Arm` (the new SDK). Common ones:

- Connect/enable: `connect`, `reconnect`, `close`, `enable`, `disable`
- Motion: `movej`, `movej_sync`, `move_p` (joint-space PTP), `home`
- Cartesian (firmware-planned): `move_l` (straight line), `move_c` (arc; start point must be the measured TCP), `move_path` (multi-waypoint)
- Query/compute: `get_state`, `get_status_now`, `get_tcp`, `ik`
- Safety: `emergency_stop`, `reset`, `clear_faults`
- Zero gravity: `zero_g` (enter + background keep-alive), `zero_g_stop` (exit)
- Continuous servo/passthrough: `move_js`, `send_mit`, `send_mit_all`
- Tuning: `set_speed`, `park`, `set_motion_mode`, `set_*` / `get_*` (dynamics and control laws)
- Licensing: `license`, `activate`

> Reflection only reaches top-level callable methods. Sub-namespaces such as
> `arm.params.*` / `arm.log.*` / `arm.diag.*` are not reachable through Node 1
> (call the SDK directly in a script if you need them).

⚠️ The new SDK does **not** have `movel`/`movec`/`fk`/`hold`/`joint_impedance`, etc.
(planning/force control are not done on the PC side; FK is only the current feedback `get_tcp()`,
there is no `fk(q)` for arbitrary joint angles).
Advanced force-control scenarios still go through `pylitearm` + server.

## Key Implementation Notes

1. **Unified JSON commands**: Node 1 publishes `{"api", "args"}` using `std_msgs/String`,
   avoiding the compile/load pitfalls of custom messages inside Isaac Sim's internal rclpy.
2. **Reflective dispatch**: Node 2 does `getattr(arm, api)(**kwargs)`, covering all APIs with one code path;
   only public callables are allowed (internal attributes starting with `_` are blocked).
3. **Isolated execution thread**: motion APIs block until completion, so Node 2 executes them
   on a separate thread. This keeps the spin thread free, so the state-publish timer never
   stalls and the simulation keeps following.
4. **Automatic enable**: the new SDK requires `enable()` before motion, so Node 2 enables
   automatically after connecting; failures are warnings only (not fatal) to aid diagnosis.
5. **Live state following**: the simulation subscribes to `/litearm/joint_state` (the robot's
   actual joint angles) and writes it with priority; trajectory subscription (the old mode)
   is kept as a fallback. State is read via `get_state().value` (a `Msg` envelope; it reads the
   firmware's 100 Hz state-stream cache rather than sending a request per read).
6. **Simulation drive unit is degrees**: the USD joint `targetPosition` is in degrees, not radians,
   so the sim node converts with `math.degrees()`.
7. **No USD writes from ROS2 callbacks**: the sim node's callback only stores the latest joint
   angles; the main loop writes the DriveAPI, avoiding deadlock.

## Safety Notes

- ⚠️ The real robot will actually move! Before running, confirm the arm is powered, the workspace is clear,
  and the e-stop is within reach.
- Node 2 enables automatically at startup (the arm becomes powered). Use `--no-enable` for a
  bring-up-only, read-only session.
- For a first run, use `"speed":0.1` in `--args` to verify at low speed, then speed up after
  confirming everything is normal.
- Zero-gravity/force-control modes make the arm go limp — always have someone hold the arm before
  executing them, and once in `zero_g` you must `zero_g_stop` to exit.
