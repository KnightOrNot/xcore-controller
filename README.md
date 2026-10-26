# xcore-controller

用 GELLO 主臂遥操作 ROKAE CR7 从臂和 Robotiq 2F-85 夹爪，并把两台相机的 RGBD、
夹爪开合和末端位姿录成 LeRobot 数据集。

本地只负责主臂输入和操作界面：GELLO 串口服务、网页／终端面板、数据拉取。
CR7 实时控制、双 D435i 采集、数据封存与转换、LeLab 浏览都在远端 Linux 主机完成，
中间只有有线网络和 SSH。

## 现状

| 已验证 | 仍需现场验收 |
| --- | --- |
| 本地 GELLO 七通道、远端 RT 跟随（小幅动作、零位移启停） | 大范围轨迹跟随 |
| 双 RGBD 无损记录、会话封存与提交协议 | 断流停止的真实表现 |
| 远端转换发布、LeLab 浏览、本地拉取与 SHA-256 校验 | 退出返回、下电、关页后的自动收尾 |
| 网页数采面板、按键入口、pose10／joints 两种表示 | 换一台新远端的完整部署 |

“代码已实现”“离线测试通过”“真机已实测”是三件不同的事，这里分开标注。
历史实施记录见 [操作手册](docs/OPERATIONS.md) 和 [docs/HISTORY.md](docs/HISTORY.md)。

## 组成

| 仓库 | 职责 |
| --- | --- |
| `xcore-controller` | 顶层入口：脚本、配置、本地／远端双角色、网页面板、拉取 |
| `xcore-sdk-python` | CR7 SDK 封装、软限位、实时跟随、末端 FK |
| `xcore-gello-software` | 本地 GELLO 串口只读采集 |
| `xcore-gripper-2F85` | Robotiq 2F-85 协议与夹爪服务 |
| `camera-realsense-d435i` | 两台 D435i 的采集、预览、无损记录 |
| `xcore-adapters` | 数据契约、字段映射、GELLO／机器人适配 |
| `xcore-dataset` | raw 封存、时间对齐、LeRobot 转换、LeLab 服务 |

`lerobot-converter` 是其他项目仍在使用的旧七维转换器，本链路不依赖它。

## 快速开始

### 1. 前提

**系统依赖。** 控制电脑需要能联网的 Ubuntu／Debian，先装 `git`、`curl`、SSH 客户端，
以及编译 Python 和后续 Python 轮子需要的库：

```bash
sudo apt update
sudo apt install -y git curl ca-certificates openssh-client build-essential \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libncurses-dev xz-utils tk-dev libffi-dev liblzma-dev \
  libgl1 libegl1 libglib2.0-0t64 ffmpeg
```

这组包名对应 Ubuntu 24.04；22.04 上 `libglib2.0-0t64` 叫 `libglib2.0-0`。

**pyenv。** 用 git 克隆到 `~/.pyenv`，再把初始化写进 `~/.bashrc`：

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

**Python 版本。** 控制链路必须是 Python 3.11.16（CR7 的 SDK 扩展是 CPython 3.11 ABI，
换版本会加载失败），数据转换用 3.12.14：

```bash
pyenv install -s 3.11.16
pyenv install -s 3.12.14
pyenv global 3.11.16
```

`pyenv install` 是在本机现场编译的，上面那组 `build-essential`、`libssl-dev` 等依赖
缺一个都会编译失败。

**uv。** 用于创建和同步各子项目的虚拟环境：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

装完确认一下：`python --version` 应显示 3.11.16，`uv --version` 应有输出。
系统自带的 Python 3.12 不用于 CR7 控制。

**远端与现场。** 远端主机必须**已经完成部署**（见[远端部署](docs/remote-deploy.md)），
且本地能用密钥免密 `ssh` 登录。硬件方面：GELLO 接本地 USB，CR7（`192.168.2.160`）、
夹爪和两台 D435i 接在远端。

### 2. 克隆

`.gitmodules` 里是 SSH 地址；没有配置 GitHub SSH 时，最后一行用
`insteadOf` 临时改走 HTTPS。已经配好密钥的可以直接 `git clone --recurse-submodules`。

```bash
mkdir -p "$HOME/projects/xcore" && cd "$HOME/projects/xcore"
git clone https://github.com/KnightOrNot/xcore-controller.git
cd xcore-controller
git -c url."https://github.com/".insteadOf=git@github.com: submodule update --init
```

### 3. 初始化环境

这一步建 5 个独立 Python 环境（控制器与各子项目）并自检，不连接硬件。

```bash
./scripts/setup.sh
```

### 4. 自检

三条命令都不上电、不激活夹爪、不发送运动目标。

```bash
./scripts/setup.sh --check-only
./xcore-sdk-python/.venv/bin/xcore-sdk-python doctor
./scripts/start_remote_record.sh --check-only
```

`doctor` 的结论在 `result` 里：`result.sdk_version` 应为 `0.7.1`，
`result.hardware_connected` 为 `false`（离线检查不连机械臂）。
`start_remote_record.sh --check-only` 会依次启动并检查远端 hardware、夹爪、本地
GELLO、两台相机和 LeLab，任何一步失败都会在进入运动前退出。

`--check-only` **结束时不停它刚启动的服务**，方便直接进入下一步；想先收工就手动停：

```bash
./scripts/stop_remote_controller.sh
./scripts/stop_camera.sh
./scripts/stop_dataset.sh
./scripts/stop_gripper.sh
```

### 5. 第一次运行

标定文件已随仓库提供，但**只对应 192.168.2.160 这台 CR7**；
换机械臂必须重新标定，见
[操作手册 · 首次标定](docs/OPERATIONS.md#6-首次标定建立主臂与从臂的对应关系)。

确认场地安全、急停可达后再运行：

```bash
./scripts/start_remote_record.sh --task "pick and place" --web --enable-motion
```

它会启动全部远端服务并打开 `http://127.0.0.1:8095` 面板；`--enable-motion` 只是
授权，真正的运动要你在网页上勾选确认并点“启动跟随”。想去掉网页、用终端按键采集，
就去掉 `--web`，那样会在启动前要一次 `y` 确认。

按 `Ctrl+C`、面板 `Q` 或直接关闭网页，都会丢弃未保存片段、按 `return_mode` 返回、
下电，并停止本次启动的远端服务；`--keep-services` 可以保留服务。日常采集用的就是
上面这条命令，只是把任务名换掉。

## 基本配置

唯一配置源是 `config/default.toml`，脚本通过 `tools/config_defaults.py` 读取。
优先级是：命令行参数 > 已存在的 `XCORE_*` 环境变量 > `config/default.toml` > 内置默认值。
用 `XCORE_CONFIG=/path/experiment.toml` 可以整体换一份配置。

| 表 | 关键项 | 说明 |
| --- | --- | --- |
| `[robot]` | `ip`、`return_mode`、`follow_max_speed_deg`、`follow_gripper` | CR7 地址；退出返回（`zero`／`start`／`none`）；软件限速 ≤75 °/s；是否跟随扳机 |
| `[gello]` | `port` | 主臂 FTDI by-id 串口，换机器要重新核实 |
| `[remote]` | `gripper_host`、`camera_ssh_target`、`gripper_port` | 远端主机与夹爪 TCP 端口 |
| `[recording]` | `raw_data_root`、`lerobot_data_root`、`raw_fps`、`task` | 本地数据根、采样频率、默认任务名 |
| `[web]` | `host`、`port`、`close_grace_s` | 面板只监听 loopback；关页面后多久自动收尾 |
| `[roles]` | 各端口、`remote_python`、`remote_data_root` | 远端运行环境与数据根（`~/project/xcore-data`） |
| `[timeouts]` | `startup_ready_s`、`conversion_wait_s` | 服务就绪、等待转换发布的上限 |

完整字段、取值范围和覆盖变量见[配置参考](docs/reference/config.md)。常用覆盖：

```bash
XCORE_RETURN_MODE=none ./scripts/start_remote_record.sh --task "调试" --check-only
./scripts/start_remote_record.sh --task "pick" --web-port 8096
```

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `./scripts/start_remote_record.sh --task T [--web] [--enable-motion]` | 一键数采（默认入口） |
| `./scripts/start_remote_controller.sh --hardware` | 只起远端运动角色与隧道 |
| `./scripts/start_gripper.sh`、`stop_gripper.sh` | 远端夹爪服务启停 |
| `./scripts/start_camera.sh`、`stop_camera.sh` | 两台相机的预览、截图、启停 |
| `./scripts/start_dataset.sh`、`stop_dataset.sh` | LeLab 浏览与网页拉取网关 |
| `./scripts/pull_dataset.sh ID REV` | 拉取已发布数据集，`--pose`／`--joints`／`--list` |
| `./scripts/convert_dataset.sh` | 触发或重试远端转换 |

全部参数见 [CLI 参考](docs/reference/cli.md)。

## 远端部署

远端需要源码副本、独立的 Python 运行环境和 5 个 systemd 用户 unit，且不在远端联网
安装依赖。完整的目录布局、步骤和版本清单见**[远端部署](docs/remote-deploy.md)**。

换到新现场时，除部署外还要改 `[robot].ip`、`[remote]` 的主机、`[gello].port`、
相机 `deploy/camN.json` 的序列号、夹爪 RS485 by-id，并重新做一次标定。

## 数据与安全

- 所有服务默认 `disabled`，不开机／登录自启，由脚本按需 `systemctl --user start`。
- 运动永远要显式授权：`--enable-motion` 只是允许，网页还要再确认一次；不加只能看状态。
- 口令、SSH 私钥、数据集、日志、`.venv` 不进 Git；标定与相机序列号按用户要求已纳入。
- 采集数据在远端 `~/project/xcore-data/`，本地拉取落在 `data/lerobot/`，都被 Git 忽略。
- 客户端超时**不等于**远端已取消：先查 `status` 和实测位姿，不要重复发运动命令。

## 文档

| 内容 | 位置 |
| --- | --- |
| 详细操作手册（安装、接线、标定、跟随、排障） | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| 文档总索引 | [docs/index.md](docs/index.md) |
| 远端部署 | [docs/remote-deploy.md](docs/remote-deploy.md) |
| 配置、CLI、错误码 | `docs/reference/` |
| 数据契约与设计 | [docs/DATASET_EE10_DESIGN.md](docs/DATASET_EE10_DESIGN.md) |
| 协作约定与历史 | [AGENTS.md](AGENTS.md)、[docs/HISTORY.md](docs/HISTORY.md) |
