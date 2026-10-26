# xcore-controller

用 GELLO 主臂遥操作 ROKAE CR7 从臂和 Robotiq 2F-85 夹爪，录制双相机 RGBD、
夹爪开合与末端位姿，输出 LeRobot 数据集。

本地只跑主臂输入和操作界面；CR7 控制、相机采集、转换和 LeLab 在远端 Linux 主机，
中间是有线网络和 SSH。

## 现状

| 已验证 | 仍需现场验收 |
| --- | --- |
| 本地 GELLO 七通道、远端 RT 跟随 | 大范围轨迹跟随 |
| 双 RGBD 无损记录、会话封存与提交协议 | 断流停止的真实表现 |
| 远端转换发布、LeLab 浏览、本地拉取与校验 | 退出返回、下电、关页后的自动收尾 |
| 网页数采面板、pose10／joints 两种表示 | 换一台新远端的完整部署 |

历史记录见 [操作手册](docs/OPERATIONS.md) 和 [docs/HISTORY.md](docs/HISTORY.md)。

## 组成

| 仓库 | 职责 |
| --- | --- |
| `xcore-controller` | 顶层入口：脚本、配置、双角色、网页面板、拉取 |
| `xcore-sdk-python` | CR7 SDK 封装、软限位、实时跟随、末端 FK |
| `xcore-gello-software` | 本地 GELLO 串口只读采集 |
| `xcore-gripper-2F85` | Robotiq 2F-85 协议与夹爪服务 |
| `camera-realsense-d435i` | 两台 D435i 的采集、预览、无损记录 |
| `xcore-adapters` | 数据契约、字段映射、GELLO／机器人适配 |
| `xcore-dataset` | raw 封存、时间对齐、LeRobot 转换、LeLab 服务 |

## 快速开始

### 1. 前提

```bash
sudo apt update
sudo apt install -y git curl ca-certificates openssh-client build-essential \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libncurses-dev xz-utils tk-dev libffi-dev liblzma-dev \
  libgl1 libegl1 libglib2.0-0t64 ffmpeg
```

Ubuntu 22.04 把 `libglib2.0-0t64` 写作 `libglib2.0-0`。

```bash
git clone https://github.com/pyenv/pyenv.git "$HOME/.pyenv"
```

```bash
cat >> "$HOME/.bashrc" <<'BASHRC'
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$HOME/.local/bin:$PATH"
eval "$(pyenv init - bash)"
BASHRC
source "$HOME/.bashrc"
```

3.11.16 用于控制链路，3.12.14 用于数据转换：

```bash
pyenv install -s 3.11.16
pyenv install -s 3.12.14
pyenv global 3.11.16
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

远端须已部署，本地须能免密 `ssh` 登录，见[远端部署](docs/remote-deploy.md)。
GELLO 接本地 USB；CR7 `192.168.2.160`、夹爪和两台 D435i 接远端。

### 2. 克隆

```bash
mkdir -p "$HOME/projects/xcore" && cd "$HOME/projects/xcore"
git clone https://github.com/KnightOrNot/xcore-controller.git
cd xcore-controller
git -c url."https://github.com/".insteadOf=git@github.com: submodule update --init
```

`.gitmodules` 是 SSH 地址；已配 GitHub SSH 的可直接 `git clone --recurse-submodules`。

### 3. 初始化环境

```bash
./scripts/setup.sh
```

### 4. 自检

```bash
./scripts/setup.sh --check-only
./xcore-sdk-python/.venv/bin/xcore-sdk-python doctor
./scripts/start_remote_record.sh --check-only
```

`doctor` 应为 `result.sdk_version` `0.7.1`、`result.hardware_connected` `false`。
`--check-only` 结束时不停止已启动的服务，需要时手动停：

```bash
./scripts/stop_remote_controller.sh
./scripts/stop_camera.sh
./scripts/stop_dataset.sh
./scripts/stop_gripper.sh
```

### 5. 第一次运行

标定文件只对应 `192.168.2.160`，换机械臂需重新标定，见
[首次标定](docs/OPERATIONS.md#6-首次标定建立主臂与从臂的对应关系)。

```bash
./scripts/start_remote_record.sh --task "pick and place" --web --enable-motion
```

面板在 `http://127.0.0.1:8095`，运动由面板“启动跟随”触发。去掉 `--web` 走终端按键，
启动前需一次 `y` 确认。

`Ctrl+C`、面板 `Q`、关闭网页都会丢弃未保存片段、按 `return_mode` 返回、下电并停止
本次启动的远端服务；`--keep-services` 保留服务。

## 基本配置

`config/default.toml` 是唯一配置源，优先级：命令行 > `XCORE_*` 环境变量 > 文件 >
内置默认值。`XCORE_CONFIG=/path/experiment.toml` 换整份配置。

| 表 | 关键项 | 说明 |
| --- | --- | --- |
| `[robot]` | `ip`、`return_mode`、`follow_max_speed_deg`、`follow_gripper` | CR7 地址；退出返回 `zero`／`start`／`none`；限速 ≤75 °/s；是否跟随扳机 |
| `[gello]` | `port` | 主臂 FTDI by-id 串口 |
| `[remote]` | `gripper_host`、`camera_ssh_target`、`gripper_port` | 远端主机与夹爪 TCP 端口 |
| `[recording]` | `raw_data_root`、`lerobot_data_root`、`raw_fps`、`task` | 本地数据根、采样频率、默认任务名 |
| `[web]` | `host`、`port`、`close_grace_s` | 面板监听地址；关页面后的收尾宽限 |
| `[roles]` | 各端口、`remote_python`、`remote_data_root` | 远端运行环境与数据根 |
| `[timeouts]` | `startup_ready_s`、`conversion_wait_s` | 服务就绪、等待转换发布的上限 |

完整字段见[配置参考](docs/reference/config.md)。

```bash
XCORE_RETURN_MODE=none ./scripts/start_remote_record.sh --task "调试" --check-only
./scripts/start_remote_record.sh --task "pick" --web-port 8096
```

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `./scripts/start_remote_record.sh --task T [--web] [--enable-motion]` | 一键数采 |
| `./scripts/start_remote_controller.sh --hardware` | 只起远端运动角色与隧道 |
| `./scripts/start_gripper.sh`、`stop_gripper.sh` | 远端夹爪服务启停 |
| `./scripts/start_camera.sh`、`stop_camera.sh` | 相机预览、截图、启停 |
| `./scripts/start_dataset.sh`、`stop_dataset.sh` | LeLab 浏览与网页拉取网关 |
| `./scripts/pull_dataset.sh ID REV` | 拉取已发布数据集，`--pose`／`--joints`／`--list` |
| `./scripts/convert_dataset.sh` | 触发或重试远端转换 |

全部参数见 [CLI 参考](docs/reference/cli.md)。

## 远端部署

远端需源码副本、Python 运行环境和 5 个 systemd 用户 unit，不在远端联网安装依赖。
见[远端部署](docs/remote-deploy.md)。

换现场还要改 `[robot].ip`、`[remote]` 主机、`[gello].port`、相机 `deploy/camN.json`
序列号、夹爪 RS485 by-id，并重新标定。

## 数据与安全

- 所有服务默认 `disabled`，由脚本按需 `systemctl --user start`。
- 运动需显式授权：`--enable-motion` 只是允许，面板还要再确认一次。
- 口令、SSH 私钥、数据集、日志、`.venv` 不进 Git。
- 客户端超时不等于远端取消：先查 `status`，不要重复发运动命令。

## 文档

| 内容 | 位置 |
| --- | --- |
| 安装、接线、标定、跟随、排障 | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| 文档总索引 | [docs/index.md](docs/index.md) |
| 远端部署 | [docs/remote-deploy.md](docs/remote-deploy.md) |
| 配置、CLI、错误码 | `docs/reference/` |
| 数据契约与设计 | [docs/DATASET_EE10_DESIGN.md](docs/DATASET_EE10_DESIGN.md) |
| 协作约定与历史 | [AGENTS.md](AGENTS.md)、[docs/HISTORY.md](docs/HISTORY.md) |
