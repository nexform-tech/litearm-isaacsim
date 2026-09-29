# Devcontainer image for litearm-isaacsim: the official Isaac Sim container plus
# the dependencies of Node 1 and Node 2 (ROS 2, pyserial, the litearm SDK).
#
# The official image runs as the rootless user isaac-sim (UID 1234). This
# Dockerfile switches back to root so the mounted workspace and the Kit caches
# stay writable from the devcontainer.
ARG ISAAC_SIM_TAG=5.1.0
FROM nvcr.io/nvidia/isaac-sim:${ISAAC_SIM_TAG}

ARG LITEARM_SDK_GIT_URL=""

USER root
ENV DEBIAN_FRONTEND=noninteractive

# The image is Ubuntu 24.04, where ROS 2 Humble does not install, so Node 1 and
# Node 2 use ROS 2 Jazzy here. Node 3 keeps the Humble rclpy bundled inside
# Isaac Sim's ros2 bridge extension; the two communicate over the default
# Fast DDS RMW, which is wire-compatible across distros.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg lsb-release python3-serial usbutils \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-ros-base ros-jazzy-ros2cli ros-jazzy-ros2launch \
    && rm -rf /var/lib/apt/lists/*

# Node 2 needs the litearm STM32 thin SDK (depends on pyserial only). Clone it
# at build time when LITEARM_SDK_GIT_URL is provided; otherwise clone it once
# into the mounted litearm-sdk volume as described in README.md.
RUN if [ -n "$LITEARM_SDK_GIT_URL" ]; then \
        git clone "$LITEARM_SDK_GIT_URL" /opt/litearm-python-gitee; \
    else \
        mkdir -p /opt/litearm-python-gitee/src; \
        echo "LITEARM_SDK_GIT_URL is empty; skipped the litearm SDK clone"; \
    fi

# USD scene assets live in the litearm-assets volume (litearm_clean.usd).
RUN mkdir -p /opt/litearm-assets

# Shell convenience for interactive terminals.
RUN echo 'source /opt/ros/jazzy/setup.bash' >> /root/.bashrc \
    && echo 'export PYTHONPATH=/opt/litearm-python-gitee/src:$PYTHONPATH' >> /root/.bashrc

ENV ACCEPT_EULA=Y \
    PYTHONPATH=/opt/litearm-python-gitee/src \
    LITEARM_SDK_SRC=/opt/litearm-python-gitee/src \
    ROS_SETUP_BASH=/opt/ros/jazzy/setup.bash \
    ISAAC_SIM_DIR=/isaac-sim \
    LITEARM_USD=/opt/litearm-assets/litearm_clean.usd \
    LITEARM_SIM_LOG=/tmp/litearm_sim_node.log

USER root
WORKDIR /workspaces
