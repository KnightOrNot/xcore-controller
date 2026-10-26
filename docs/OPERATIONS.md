# 操作手册（原 README）

本文件是 xcore-controller 的详细操作手册：安装、接线、标定、跟随、夹爪、相机、
数模转换与历史排障记录。**新用户请先读 [README](../README.md)**，需要细节时再回到这里。

其中的“阶段 2/3/4”“2026-10-22/26”等小节是当时的实施记录，可能已被后续改动覆盖；
以代码、`config/default.toml` 和当前实测为准。

---

# xcore-controller：GELLO → CR7 跟随与远程相机

本指南从 **Ubuntu 24.04、x86_64 的空白控制电脑**开始，完成安装、通信、标定和真机跟随。
统一客户端读取一次 GELLO，将六轴目标发给 CR7，将扳机目标发给独立 Robotiq 2F-85 服务。
CR7 保持六轴接口。首次完成以下步骤后，每次实验使用文末的[日常启动命令](#8-日常启动)。

远程双 D435i 相机可以独立启停，不需要启动跟随，见[相机快速启动](#11-远程双-d435i-相机)。
后续 AI 协作先阅读 [AGENTS.md](../AGENTS.md)，其中记录工程边界、现场配置与当前任务。

**2026-10-22 新架构进度**：本地 GELLO 服务、远端 SDK 只读 worker、数据桥、
远端运动 worker／主臂映射／vendor FK 已实现；合成数据 LeRobot 转换、LeLab 浏览和
本地拉取已验收。远端真机运动、连续多流采集仍需现场验收，不能把代码存在当作已部署。
新入口、现场硬件检查及剩余工作见 [远端数据阶段说明](REMOTE_DATA_MILESTONE.md)。
下文原有跟随命令仍使用旧链路，不要与远端 SDK 会话同时运行。

## 默认配置

所有可复现的默认参数集中在 [config/default.toml](../config/default.toml)：CR7 地址、
GELLO 串口、远端夹爪/相机主机、跟随限速、记录路径和超时。优先级为
命令行参数 > 已存在的 `XCORE_*` 环境变量 > TOML > 脚本内置默认值。
使用 `XCORE_CONFIG=/path/experiment.toml ./scripts/...` 可以选择另一份配置。

原有五个 submodule 各自提供 `config/default.toml`，由各自 CLI 的 `--config` 覆盖。
新增 `xcore-adapters`、`xcore-dataset` 已作为独立 submodule 引入；dataset 有独立配置，
adapter 是无设备访问的数据包。新入口环境安装见[首阶段说明](REMOTE_DATA_MILESTONE.md)。
现场标定、退出姿态、相机 JSON 和数据集仍是 Git 忽略的现场文件，不写入默认配置。
详见[配置参考](reference/config.md)、[子模块配置](reference/submodule-config.md)
和[架构说明](index.md)；安装、相机与排障见 [docs/](index.md)。

本仓库的 shell 命令统一位于 `scripts/`，以下命令均从 `xcore-controller` 根目录执行：

| 命令 | 用途 |
| --- | --- |
| `./scripts/setup.sh` | 初始化子模块和独立 Python 环境 |
| `./scripts/start_gello_follow.sh` | 六轴＋夹爪跟随；真实运动需 `--enable-motion` |
| `./scripts/start_data_record.sh` | 旧七维跟随记录；加 `--remote` 使用新远端链路 |
| `./scripts/start_remote_record.sh` | 新链路数采：本地 GELLO＋bridge＋远端 SDK／双相机 |
| `./scripts/start_remote_record.sh --web` | 同一入口启动本地网页数采面板 |
| `./scripts/convert_dataset.sh` | 远端转换排队／执行／重试／查看 |
| `./scripts/start_gripper.sh` | 按需启动远端夹爪服务 |
| `./scripts/stop_gripper.sh` | 完全停止远端夹爪服务；先结束跟随及退出返回 |
| `./scripts/start_camera.sh` | 按需启动双相机服务并预览 |
| `./scripts/stop_camera.sh` | 完全停止双相机远端服务并清理隧道 |
| `./scripts/start_gello_service.sh` | 新架构本地 GELLO 只读服务，默认不连接 CR7 |
| `./scripts/start_remote_controller.sh --hardware-read-only` | 启动远端 SDK 只读服务及本地隧道，不支持启用运动 |
| `./scripts/start_remote_controller.sh --hardware` | 启动可运动的远端 SDK worker；仍需显式 `arm` |
| `./scripts/stop_remote_controller.sh` | 停止新架构远端只读／模拟／运动服务 |
| `./scripts/start_dataset.sh` | 启动远端 LeLab、本地隧道及格式可选的网页拉取入口 |
| `./scripts/stop_dataset.sh` | 停止远端数据浏览服务 |
| `./scripts/pull_dataset.sh [--pose\|--joints] ID REVISION` | 拉取对应表示的数据集；`--list` 查看可用版本 |

遇到 `J1(+183.5° 限 -180~+180°)` 时，是本地跟随限位拒绝启动，
不是主臂串口或夹爪网络连接失败。主从对齐误差很小与姿态是否在限位内是两项独立检查。
准备阶段与 RT 驱动现在共用限位交集，会在准备上电／移动前报告超限关节。
请先将主臂映射目标和 CR7 当前姿态调整到允许范围内，再重新启动。
完整范围及处理说明见 [SDK 跟随说明](../xcore-sdk-python/README.md#2-预览再启动跟随)。

## 1. 接线与地址

| 设备 | 连接方式 | 本指南使用的配置 |
| --- | --- | --- |
| 控制电脑 | WiFi 联网；有线连接机器人网络 | 有线 `192.168.2.100/24` |
| GELLO 主臂 | USB 接控制电脑 | 六轴 ID 1～6，夹爪扳机 ID 7，57600 baud |
| CR7 从臂 | 以太网接机器人网络 | `192.168.2.160`，控制器版本 ≥ 3.2.1 |
| 夹爪服务电脑 | 与控制电脑有线互通 | `192.168.2.225`，SSH 用户 `rokae`，TCP 5005 |
| Robotiq 夹爪 | USB/RS485 接夹爪服务电脑；夹爪另接电源 | 串口与 GELLO 的串口不同 |

控制电脑需要同时能访问 `.160` 和 `.225`，例如通过同一交换机连接。
表中的 IP、用户名和串口是当前现场配置；换设备时按实际值修改。
本文命令默认在**控制电脑的 `xcore-controller` 根目录**执行；远端步骤会单独标明。

启动对齐会移动从臂。开始前确认机械臂空闲、软限位已开启、示教器无报警且允许 SDK 控制，
确认到目标姿态的运动范围可用；对齐期间保持 GELLO 不动。夹爪服务启动会激活夹爪。

## 2. 安装系统依赖、Python 和项目

### 2.1 安装工具

先让控制电脑通过 WiFi 正常联网，在 Bash 终端执行：

```bash
sudo apt update
sudo apt install -y git curl ca-certificates openssh-client build-essential \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libncurses-dev xz-utils tk-dev libffi-dev liblzma-dev \
  libgl1 libegl1 libglib2.0-0t64 ffmpeg
```

安装 pyenv：

```bash
git clone https://github.com/pyenv/pyenv.git "$HOME/.pyenv"
```

将 .pyenv 加入到系统中：

```bash
cat >> "$HOME/.bashrc" <<'BASHRC'
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$HOME/.local/bin:$PATH"
eval "$(pyenv init - bash)"
BASHRC
source "$HOME/.bashrc"
```

安装 uv：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

使用 pyenv 管理环境中的 python 版本：

```bash
# 控制环境为 3.11，数据转换环境为 3.12
pyenv install -s 3.11.16
pyenv install -s 3.12.14
pyenv global 3.11.16
python --version
uv --version
```

安装方式参考 [pyenv 官方说明](https://github.com/pyenv/pyenv#installation)、
[Python 构建依赖](https://github.com/pyenv/pyenv/wiki#suggested-build-environment)和
[uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)。
Ubuntu 自带的 Python 3.12 不用于 CR7 控制；SDK 扩展要求 CPython 3.11。

### 2.2 克隆与初始化

以下使用 HTTPS，无需先配置 GitHub SSH 密钥。已有 clone 时进入现有目录，从子模块初始化开始。

```bash
mkdir -p "$HOME/projects/xcore"
cd "$HOME/projects/xcore"
git clone https://github.com/KnightOrNot/xcore-controller.git
cd xcore-controller
```

clone submodule：

```bash
# .gitmodules 使用 SSH URL；本次初始化临时转为 HTTPS
git -c url."https://github.com/".insteadOf=git@github.com: \
  submodule update --init
```

运行脚本初始化 submodule：

```bash
./scripts/setup.sh --skip-submodules
./scripts/setup.sh --check-only
./xcore-sdk-python/.venv/bin/xcore-sdk-python doctor
```

如仓库需要访问权限，使用有权限的 GitHub 凭据；已配置 GitHub SSH 的用户也可直接运行
`./scripts/setup.sh`，让脚本初始化子模块。跟随使用 PyPI 的 `dynamixel-sdk`，
无需额外安装 `third_party/DynamixelSDK/python`，也无需初始化仿真模型的嵌套子模块。

`scripts/setup.sh` 安装五个独立环境，包括数据转换及相机客户端，不连接硬件。
最后应显示“五个子项目的环境与命令入口检查通过”；`doctor` 应返回 `ok: true`、
`sdk_version: 0.7.1`、`hardware_connected: false`。这里的 `false` 表示离线检查未连接机械臂。
后续使用顶层 `.sh`，**不需要手动激活 `.venv`**。

**SDK 二进制已随子模块提供，无需下载或复制**，路径为：

```text
xcore-sdk-python/Release/linux/xCoreSDK_python.cpython-311-x86_64-linux-gnu.so
```

它适用于本指南的 Linux x86_64、CPython 3.11。其他架构或解释器需匹配库。
现场标定文件仍不纳入 Git，首次使用按第 6 节生成。

## 3. 配置有线通信

有线网卡只负责机器人同网段通信，WiFi 提供默认路由和 DNS。
不要给直连机器人的有线配置设置默认网关。以下创建持久 NetworkManager 配置，安装时执行一次。如果连上网线后，系统仍然能够连接上 WiFi 并且可以实现与机械臂的网线通信，则可跳过该步。

```bash
nmcli device status
nmcli connection show

# 替换为上面显示的实际有线网卡名；不要填写 WiFi 网卡
wired_interface=enx0024321865b3
sudo nmcli connection add type ethernet ifname "$wired_interface" \
  con-name cr7-direct connection.autoconnect yes connection.autoconnect-priority 100 \
  ipv4.method manual ipv4.addresses 192.168.2.100/24 \
  ipv4.gateway "" ipv4.dns "" ipv4.never-default yes \
  ipv4.ignore-auto-dns yes ipv4.route-metric 700 ipv6.method disabled
sudo nmcli connection up cr7-direct

ip -4 address show dev "$wired_interface"
ip -4 route get 192.168.2.160
ip -4 route get 192.168.2.225
curl -I --connect-timeout 10 https://github.com
```

两条 `route get` 应走有线网卡，源地址为 `192.168.2.100`；最后一条应能访问外网。
该配置断线重插后仍生效。已有正确的有线配置时跳过创建，不要重复添加同名配置。
`never-default` 的含义见 [NetworkManager IPv4 文档](https://networkmanager.dev/docs/api/latest/settings-ipv4.html)。

如果更换了本机或机器人地址，在**每次运行跟随的终端**设置：

```bash
export XCORE_ROBOT_IP=192.168.2.160
export XCORE_LOCAL_IP=192.168.2.100
export XCORE_GRIPPER_HOST=192.168.2.225
export XCORE_GRIPPER_SSH_USER=rokae
```

换网段时还要相应修改 `cr7-direct` 的 IPv4 地址，环境变量不会配置网卡。
仅在没有其他 SDK 会话、机械臂空闲时做连接检查：

```bash
./xcore-sdk-python/.venv/bin/xcore-sdk-python status \
  --ip 192.168.2.160 --local-ip 192.168.2.100
```

应返回 `ok: true`、六轴关节反馈和机器人信息；单纯 ping 通不能替代 SDK 连接检查。

## 4. GELLO 串口权限和设备识别

GELLO 接控制电脑，Robotiq 的 RS485 适配器接夹爪服务电脑。
在控制电脑执行：

```bash
sudo usermod -aG dialout "$USER"
```

**注销桌面并重新登录**，使组权限生效；然后打开新终端：

```bash
cd "$HOME/projects/xcore/xcore-controller"
id -nG
ls -l /dev/serial/by-id/

# 填写本机实际 GELLO 路径；当前现场默认如下
export XCORE_GELLO_PORT=/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0

test -r "$XCORE_GELLO_PORT" && test -w "$XCORE_GELLO_PORT" && echo "GELLO 串口权限正常"
```

`id -nG` 应包含 `dialout`。推荐使用稳定的 `by-id` 路径；`/dev/ttyUSB0` 可能随插拔变化。
环境变量仅在当前终端生效，换终端时重新设置实际路径。当前适配器名称与默认值一致时无需设置。
后续不要同时运行其他 GELLO 读取、仿真或串口调试程序。

## 5. 启动夹爪服务

### 5.1 现场已经有后台服务

当前 `.225` 系统已安装 `xcore-gripper-follow.service`。若继续使用这台系统，
只需完成 SSH 登录设置和服务检查，**跳过 5.2 的首次部署**。

2026-10-21 现场项目已迁移到远端 `~/project/xcore-gripper-follow/`。
`current` 使用相对链接指向 `releases/` 中的部署版本；systemd 的 `WorkingDirectory`
为 `/home/rokae/project/xcore-gripper-follow/current`，`PYTHONPATH` 为该目录下的 `src`。
夹爪服务已取消开机／登录自启，由本地 `./scripts/start_gripper.sh` 通过 SSH 按需启动。
`Linger=yes` 保留，用于启动后在 SSH 断开时继续运行，不会自动启动已 disabled 的服务。
迁移前的 unit、部署记录、链接和代码校验值备份在远端
`~/.local/state/xcore-gripper-migrations/20261021T160259+0800/`。
迁移后已通过服务停止／启动及本机的 `scripts/start_gripper.sh`、`--status`、SDK
`gripper-check` 检查；没有为此重启整台电脑或测试夹爪开合。
以后再次移动目录时，应同步修改服务路径并执行 `systemctl --user daemon-reload`；
先结束跟随与退出返回，再重启夹爪服务，避免引发断流故障。

在夹爪服务电脑的终端执行以下命令启用 SSH；已启用时跳过：

```bash
# 此步骤需要该电脑能访问 Ubuntu 软件源，可先连接 WiFi
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
hostname -I
```

在控制电脑执行（远端用户名或地址不同则替换）：

```bash
# 没有 SSH 密钥时创建；已有时保留原密钥
if [ ! -f "$HOME/.ssh/id_ed25519.pub" ]; then
  ssh-keygen -t ed25519
fi
ssh-copy-id rokae@192.168.2.225
ssh rokae@192.168.2.225 'hostname'
```

首次连接核对远端主机指纹；`ssh-copy-id` 按提示输入远端账户密码。
顶层管理脚本使用非交互 SSH，需密钥登录可用；密钥有口令时先在当前会话用 `ssh-add` 解锁。

```bash
./scripts/start_gripper.sh
./scripts/start_gripper.sh --status
```

预期打印“远端夹爪服务已就绪”，有 `streaming: true`、`stream_error: null` 和实际 `position_raw`。
已有服务不会重启。如果上次退出留下单纯的“目标断流超时”，入口会在取得跟随锁、
确认没有跟随／退出返回任务后自动发送 `stop` 清除锁定，再检查反馈；不重新激活或开爪。
`--status` 始终只读。串口、电源等其他故障仍会报错，不自动清除。
新系统显示“Unit ... not found”时继续执行 5.2。

### 5.2 新夹爪服务电脑：首次部署

这一节安装支持连续跟随的服务，供顶层 `scripts/start_gripper.sh` 管理。
SSH 设置按 5.1 完成；远端需有 `/usr/bin/python3`（Python ≥ 3.9）。
源码和 `pyserial` 由控制电脑打包传过去，**部署阶段远端无需访问外网或安装 uv/pyenv**。

先在夹爪服务电脑操作，给实际服务账户串口权限，并辨认夹爪适配器：

```bash
sudo usermod -aG dialout "$USER"
ls -l /dev/serial/by-id/
```

重新登录该账户／重新建立 SSH 会话，使组权限生效。当前夹爪适配器为
`usb-FTDI_USB_TO_RS-485_DAAQMP8J-if00-port0`；另一台设备需使用自己的实际路径。
先结束占用该串口或 5005 端口的旧夹爪服务，保持只运行一个服务实例。

**在控制电脑的项目根目录打包并传输：**

```bash
gripper_bundle_dir="$(mktemp -d)"
git -C xcore-gripper-2F85 archive HEAD | tar -xf - -C "$gripper_bundle_dir"
uv pip install --python ./xcore-sdk-python/.venv/bin/python \
  --target "$gripper_bundle_dir/vendor" pyserial==3.5
tar -czf /tmp/xcore-gripper-service.tar.gz -C "$gripper_bundle_dir" .
scp /tmp/xcore-gripper-service.tar.gz rokae@192.168.2.225:/tmp/
ssh rokae@192.168.2.225
```

**以下命令在刚登录的远端 SSH 终端执行。** `GRIPPER_SERIAL_PORT` 一行需使用远端实际夹爪串口。
这是新系统部署；已有现场后台服务直接使用 5.1。

```bash
mkdir -p "$HOME/xcore-gripper-service" "$HOME/.config/systemd/user"
tar -xzf /tmp/xcore-gripper-service.tar.gz -C "$HOME/xcore-gripper-service"

cat > "$HOME/xcore-gripper-service/start_server.sh" <<'SERVER'
#!/usr/bin/env bash
set -Eeuo pipefail
service_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$service_dir/src:$service_dir/vendor"
exec /usr/bin/python3 -m xcore_gripper_2f85.gripper_server \
  --host 0.0.0.0 --port 5005 --serial-port "${GRIPPER_SERIAL_PORT:?未配置夹爪串口}"
SERVER
chmod +x "$HOME/xcore-gripper-service/start_server.sh"

cat > "$HOME/.config/systemd/user/xcore-gripper-follow.service" <<'UNIT'
[Unit]
Description=Robotiq 2F-85 continuous follow service
After=network.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
Environment=GRIPPER_SERIAL_PORT=/dev/serial/by-id/usb-FTDI_USB_TO_RS-485_DAAQMP8J-if00-port0
ExecStart=%h/xcore-gripper-service/start_server.sh
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user disable xcore-gripper-follow.service
exit
```

此时只安装服务且保持 disabled，不在远端自动激活夹爪。回到本地执行下一步启动命令后，
服务应为 `active (running)`，监听 `0.0.0.0:5005`；控制电脑连接 `192.168.2.225:5005`。
为允许 SSH 断开后用户服务继续运行，在远端执行 `sudo loginctl enable-linger "$USER"`。
这不会启用设备服务的开机自启。防火墙已启用且阻断连接时，在远端允许控制电脑访问：
`sudo ufw allow from 192.168.2.100 to any port 5005 proto tcp`。

回到**控制电脑**检查：

```bash
./scripts/start_gripper.sh
./scripts/start_gripper.sh --status
```

如果夹爪 USB 实际接在控制电脑，改在一个独立终端运行本机服务并保持终端打开：

```bash
./scripts/start_gripper.sh --local \
  --serial-port /dev/serial/by-id/usb-FTDI_USB_TO_RS-485_DAAQMP8J-if00-port0
```

随后跟随命令添加 `--gripper-host 127.0.0.1`；可用 SDK 的只读检查确认：
`./xcore-sdk-python/.venv/bin/xcore-sdk-python gripper-check --gripper-host 127.0.0.1`。
本机模式必须指定真实夹爪串口，不能使用 GELLO 的 FTDI 串口。

## 6. 首次标定：建立主臂与从臂的对应关系

新 clone 没有 `xcore-sdk-python/config/cr7_calib.json`，需生成一次。
已有本套硬件的有效现场标定时可恢复该文件并跳过本节；不能套用其他装配的偏移。

将 **GELLO 六轴摆到与 CR7 六轴 `[0°, 0°, 0°, 0°, 0°, 0°]` 对应的标准姿态**，保持不动。
夹爪服务先就绪，然后在控制电脑执行：

```bash
./scripts/start_gello_follow.sh --enable-motion --calibrate-zero
```

输入 `y` 后，脚本把 CR7 六轴移动至 0°，采集 GELLO 偏移并保存标定，随后直接进入六轴与夹爪跟随。
**这条命令会真实运动**；不能将任意主臂姿态当作标准零位。
标定成功后按 Ctrl+C 结束，再按第 7 节检查方向并实验。只标定六轴时可加 `--arm-only`。

已有文件不会覆盖。需要重新标定时指定新文件，并在后续启动中使用同一个路径：

```bash
./scripts/start_gello_follow.sh --enable-motion --calibrate-zero \
  --calib ./xcore-sdk-python/config/cr7_calib_new.json
# 后续启动
./scripts/start_gello_follow.sh --enable-motion \
  --calib ./xcore-sdk-python/config/cr7_calib_new.json
```

默认六轴方向为 `[1, 1, 1, 1, 1, 1]`，单姿态标定只确定偏移，不能自动推断方向。
不同装配需要指定方向时，先用示教器将从臂与主臂摆到已知相同关节姿态，保持两臂不动，
再执行只读标定（示例将第 2 轴方向设为 `-1`，其余为 `+1`）：

```bash
./xcore-sdk-python/.venv/bin/xcore-sdk-python follow-calibrate --ref-current \
  --ip 192.168.2.160 --local-ip 192.168.2.100 --serial "$XCORE_GELLO_PORT" \
  --signs 1 -1 1 1 1 1 --save ./xcore-sdk-python/config/cr7_calib_new.json
```

按实际装配填写六个方向，保存路径必须不存在；`--ref-current` 要求两臂已经处于对应姿态。
备份生成的标定文件，更换 GELLO 零位、装配或轴方向后重新标定。

## 7. 预览、对齐和六轴＋夹爪跟随

### 7.1 只读预览

有标定且夹爪服务就绪后执行：

```bash
./scripts/start_gello_follow.sh --show-state
```

不发送六轴或夹爪运动目标。逐轴小幅移动 GELLO，检查映射后的 `leader` 方向和角度；
开合扳机，检查 `gripper_target` 是否在 0～1 间变化。预览时实际 `robot` 和
`gripper_feedback.position_raw` 应保持实际从臂反馈。按 Ctrl+C 结束预览。

预览会显示启动偏差；只读模式允许两臂不对齐，不能移动从臂消除偏差。
真实跟随要求对齐误差在约 `17.2°` 闸门以内，下面的真实运动入口会先自动对齐。
`Dry-run only`／`dry-run` 表示只读模式，终端没有连续状态输出也不代表跟随已启用。

### 7.2 启动真实跟随

保持 GELLO 在希望从臂到达的姿态，确认运动路径，然后执行：

```bash
./scripts/start_gello_follow.sh --enable-motion
```

输入 `y` 后，先用已有标定对齐六轴到 **GELLO 当前姿态**，到位后自动进入跟随。
日常启动不要求主臂归零，也不重新标定。准备期间保持主臂静止，出现“对齐完成”并启动
客户端后再移动。依次小幅移动六个关节，再开合扳机，检查从臂六轴与实际夹爪均跟随。
夹爪目标从实时跟随开始发送，六轴对齐阶段不执行夹爪姿态对齐。

| 参数 | 默认值与说明 |
| --- | --- |
| `--max-speed-deg` | `75°/s`，实时六轴速度软件上限；允许 `0 < V <= 75` |
| `--prepare-speed` | `4000 mm/s`，启动对齐的 SDK 参数上限，允许 5～4000 |
| 六轴加速度 | `40°/s²`；短距离跟随可能达不到设定速度 |
| `--hz` / `--gripper-hz` | 六轴 50 Hz／独立夹爪 5 Hz |
| `--gripper-speed` / `--gripper-force` | `150`／`0`，夹爪参数范围 0～255 |
| `--gripper-open-deg` / `--gripper-close-deg` | GELLO 扳机角度端点 `194.8°`／`153°` |
| `--gripper-open-pos` / `--gripper-closed-pos` | 从臂夹爪原始位置端点 `0`／`255`，按实测调整 |

`75°/s` 是软件上限；`4000` 是 SDK 速度参数，不能解释为每轴 4000°/s，
也不能据此认定实际硬件最大速度。当前默认配置采用这两个上限；首次检查可明确降低：

```bash
./scripts/start_gello_follow.sh --enable-motion --max-speed-deg 10 --prepare-speed 50
# 已确认现场范围后，按需要调节实时速度与对齐速度
./scripts/start_gello_follow.sh --enable-motion --max-speed-deg 30 --prepare-speed 1000
```

每次换参数先 Ctrl+C 结束上一次跟随。命令行优先于环境变量，再优先于脚本默认值。
`XCORE_FOLLOW_MAX_SPEED_DEG`、`XCORE_PREPARE_SPEED` 可设置速度；也可修改顶层脚本开头的默认值。
夹爪端点、速度和力度都可通过表中参数覆盖，例如：

```bash
./scripts/start_gello_follow.sh --enable-motion \
  --gripper-open-deg 194.8 --gripper-close-deg 153 \
  --gripper-open-pos 0 --gripper-closed-pos 230 --gripper-speed 150 --gripper-force 30
```

仅测试六轴时运行 `./scripts/start_gello_follow.sh --enable-motion --arm-only`，无需夹爪服务。
`--arm-only` 不能与 `--gripper-host` 同用。
默认只输出启动、错误及停止信息，需要连续状态时加 `--show-state`。

**结束实验：按 Ctrl+C，等待六轴返回后退出。** 脚本先停止跟随和夹爪、
关闭实时／准备 SDK 会话，再执行退出返回。返回目标由 `config/default.toml` 的
`[robot].return_mode` 控制，默认 `zero`：

| `return_mode` | 退出返回目标 |
| --- | --- |
| `zero`（默认） | 返回六轴 0° |
| `start` | 每次启动跟随／记录前通过只读反馈记录当前六轴姿态；安全退出、主动退出和故障退出都返回该姿态 |
| `none` | 不自动返回，等价于 `--no-return` |

命令行 `--return-mode start|zero|none` 优先于配置文件；也可设置
`XCORE_RETURN_MODE` 覆盖。`start` 模式在启动对齐前采集姿态，写入本次会话的
`logs/follow-*/exit_pose.json`，不会修改现场文件。启动采集失败会在任何运动前中止。
`zero` 模式在启动前生成六轴 0° 目标，不需要额外姿态文件。
每次会话仍保存独立的 `logs/follow-*/exit_pose.json` 快照；返回结果保存为
`return-pose.json`。返回速度与等待时间沿用 `--prepare-speed`（默认 `4000 mm/s`）和
`--prepare-motion-timeout`（默认 `600 s`）；完成后恢复返回前的电源状态和模式。
夹爪保持停止，不自动开爪。确认返回路径可用；返回期间再次 Ctrl+C 会请求停止并等待 SDK 关闭。

**故障退出也默认尝试返回同一目标。** 先停止跟随并关闭记录、释放 SDK，再尝试一次实时故障恢复。
故障返回完成后下电、切手动模式，不自动重启跟随，保留原始非零退出码。
急停、安全门、其他非空闲状态、超限、恢复失败或再次触发保护时停止并报错，
不自动复位急停、不关闭碰撞检测、不循环尝试恢复。
只读预览不执行返回；跟随运行期间的 Ctrl+C、SIGTERM、正常结束和故障退出都会请求返回；
强制终止 SDK 子进程会跳过返回。返回期间不要另开 SDK 会话。
仅希望停止并保持当前姿态时，使用 `--return-mode none` 或 `--no-return`
（旧 `--no-return-zero` 仍兼容）：

```bash
./scripts/start_gello_follow.sh --enable-motion --no-return
./scripts/start_data_record.sh --task "pick up the object" --return-mode none
```

独立 SDK 命令为 `uv run --project xcore-sdk-python xcore-sdk-python return-pose`；
如需固定姿态文件，仍可直接使用 `return-pose --pose-file FILE`，但启动器的返回模式
只保留 `start`、`zero`、`none`。旧 `return-zero` 兼容入口保留。

紧急情况使用设备硬件急停；终端退出不能替代硬件急停。

## 8. 日常启动

安装、网络和标定完成后，每次在控制电脑执行以下流程即可。
按实际设备设置 `XCORE_GELLO_PORT`；使用新标定文件时给预览和跟随均添加 `--calib`。

```bash
cd "$HOME/projects/xcore/xcore-controller"
export XCORE_GELLO_PORT=/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0

# 1. 启动并检查远端夹爪服务；已有服务不重启
./scripts/start_gripper.sh

# 2. 可选：只读查看六轴／扳机；结束后按 Ctrl+C
./scripts/start_gello_follow.sh --show-state

# 3. 主臂保持期望姿态；输入 y，等待对齐完成再移动主臂
./scripts/start_gello_follow.sh --enable-motion
# 实验结束按 Ctrl+C，等待从臂六轴返回启动前记录的姿态并退出
```

远端地址或账户变化时，在同一终端设置
`XCORE_GRIPPER_HOST` / `XCORE_GRIPPER_SSH_USER`；CR7 和本机地址变化时设置
`XCORE_ROBOT_IP` / `XCORE_LOCAL_IP`。只用六轴可跳过夹爪检查，跟随命令加 `--arm-only`。

## 9. 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 插网线后不能上网 | 第 3 节确保活动有线配置为静态地址、无网关／DNS、`never-default=yes`；WiFi 保持联网 |
| `pyenv: python: command not found` | `pyenv versions` 确认已装 3.11.16，执行 `pyenv global 3.11.16`，重新打开终端 |
| 找不到 SDK 扩展 | 初始化并更新 SDK 子模块；检查第 2 节的 `.so` 存在，解释器是 3.11，架构是 x86_64，再运行 `doctor` |
| GELLO 串口不存在／无权限 | 检查 `by-id` 和 `XCORE_GELLO_PORT`；加入 `dialout` 后重新登录 |
| 缺少标定 | 执行第 6 节；正常 clone 不带现场 `cr7_calib.json` |
| 只预览、不运动 | 命令必须有 `--enable-motion`，并输入 `y`；裸 `.sh` 是 dry-run |
| `Connection refused`（夹爪） | 服务需运行在 RS485 所在电脑；检查 `.225:5005`，不能将 `0.0.0.0` 当远端地址 |
| SSH 登录失败 | 手工 `ssh rokae@192.168.2.225` 核对地址、用户、主机指纹和密钥；配置 `ssh-copy-id`，有口令时 `ssh-add` |
| `Unit ... not found` | 新远端尚未部署用户服务，执行 5.2；服务属于部署时使用的那个账户 |
| 夹爪服务不支持 streaming | 旧 demo 只有 open/close/move，需部署本项目服务，支持 follow_status/set_target/stop |
| Modbus 回复长度不足／旧服务 `IndexError` | 确认夹爪电源、RS485 接线、真实夹爪串口；本机 GELLO FTDI 不能当 Robotiq 串口 |
| `Gripper target stream timed out` | 等跟随／退出返回退出，再执行 `./scripts/start_gripper.sh` 自动清除超时锁定；`--status` 仅查看，`--reset-stream` 可手动清除 |
| 对齐失败／主臂移动／超限 | 保持主臂静止，核对标定、目标和示教器；准备每轴最大跨度 180°，到位等待 600 s；失败后检查实际姿态再重试 |
| “已有跟随启动流程正在运行” | 结束上一跟随／记录进程，等待退出；不要同时启动两个入口 |

夹爪故障排查命令（在控制电脑执行）：

```bash
./scripts/start_gripper.sh --status
ssh rokae@192.168.2.225 'systemctl --user status xcore-gripper-follow.service --no-pager'
ssh rokae@192.168.2.225 'journalctl --user -u xcore-gripper-follow.service -n 50 --no-pager'
# 先结束跟随；需要重启时执行（重启会激活夹爪）
./scripts/start_gripper.sh --restart
```

实验结束并等待退出返回完成后，可完全停止夹爪服务：

```bash
./scripts/stop_gripper.sh
```

该入口复用跟随锁，仍在跟随／退出返回时拒绝执行。它停止远端服务并释放串口，
不执行夹爪开合，也不重新启用开机自启。可用 `--gripper-host` 和 `--ssh-user` 覆盖目标。

跟随日志在 `xcore-sdk-python/logs/follow-*/`：`preparation.json` 是对齐结果，
`server.log` 是服务端日志。六轴跟随已实测；默认高速度对齐和夹爪全行程跟随仍需按现场逐项验收。

## 10. 更新与数据记录

更新到控制器固定的子模块版本，结束实验后执行；不用 `submodule update --remote`：

```bash
git pull --ff-only
git submodule sync
git -c url."https://github.com/".insteadOf=git@github.com: submodule update --init
./scripts/setup.sh --skip-submodules
./scripts/setup.sh --check-only
```

远端夹爪部署目录独立于本机子模块；本机更新不会自动更新远端服务。

需要记录从臂反馈时，使用记录入口代替普通跟随入口：

```bash
./scripts/start_gripper.sh
./scripts/start_data_record.sh --task "pick up the object"
```

它先对齐再跟随；R 开始记录、S 保存、D 丢弃、P 查看状态、H 帮助。
Ctrl+C 或故障退出后先关闭记录和跟随、处理六轴退出返回，再转换已保存片段；
恢复／返回动作不写入 episode，未保存片段保留为 `.partial`。
未保存片段保留为 `.partial`。原始数据在 `data/raw/`，LeRobot 数据在 `data/lerobot/`。

工程细节与原 README 内容见 [docs/DEVELOPMET.md](DEVELOPMET.md)；
扩展说明见 [数据记录](DATA_RECORDING.md)、[现场夹爪服务管理](GRIPPER_SERVER_UPDATE.md)。

## 11. 远程双 D435i 相机

相机接在 `rokae@192.168.2.225`，项目部署于远端 `~/project/camera-realsense-d435i/`。
控制仓库仅通过 `camera-realsense-d435i` 子模块引用相机实现。
两台相机分别提供 RGB＋深度页面，独立于机械臂和夹爪，可单独操作：

```bash
# 首次初始化并安装本地客户端；已有环境则跳过
git submodule update --init camera-realsense-d435i
uv sync --locked --no-dev --project camera-realsense-d435i

# 建立 SSH 隧道、启动两台采集并打开两个页面
./scripts/start_camera.sh
# 无桌面或希望自己打开页面
./scripts/start_camera.sh --no-open

./scripts/start_camera.sh status
./scripts/start_camera.sh info
./scripts/start_camera.sh snapshot
./scripts/start_camera.sh stop
# 完全停止远端相机进程，并关闭对应本地隧道
./scripts/stop_camera.sh
# 仅停止第二台；第一台不受影响
./scripts/stop_camera.sh --camera cam2
```

本地页面为 <http://127.0.0.1:8086>（cam1，序列号 349522071221）和
<http://127.0.0.1:8087>（cam2，序列号 349522072318）。
`./scripts/start_camera.sh --camera cam2` 只启动第二台；`./scripts/start_camera.sh status --camera cam1`
只查第一台。默认地址由 `XCORE_CAMERA_SSH_TARGET=rokae@192.168.2.225` 覆盖，需 SSH 密钥登录。

关闭网页不会停止采集；`stop` 会释放相机。`./scripts/start_camera.sh disconnect` 只关隧道，
应先执行 `stop`。远端 API 服务已取消开机／登录自启，本地启动命令会先按需启动服务，
再打开相机；SSH 服务保持可用，以接收这些命令。
截图默认保存在运行目录 `captures/cam1/`、`captures/cam2/` 下，包含 RGB JPEG、原始
16 位深度 PNG 和标定／时间元数据；这些画面不提交 Git。

当前两台以 USB 2.1 连接，已实测同时 640×480、15fps 采集及四路 MJPEG。
cam2 测试时有效深度较少，需检查现场朝向／遮挡和距离。
深度为原生视角，未对齐 RGB；两台没有硬同步，也尚未接入机械臂数据记录。
完整 CLI、部署和验收边界见 [相机 README](../camera-realsense-d435i/README.md) 与
[相机开发文档](../camera-realsense-d435i/docs/DEVELOPMENT.md)。

## 远端运动角色（2026-10-22 阶段 2）

`--hardware` 只负责连接 SDK、读取反馈和准备 FK，**不会自行上电或运动**。
必须同时运行本地 GELLO 服务和数据桥，远端才能在收到主臂样本后开始跟随：

```bash
./scripts/start_gello_service.sh
./scripts/start_remote_controller.sh --hardware
uv run xcore-controller bridge --leader-url http://127.0.0.1:9011 --remote-url http://127.0.0.1:9012
```

只读检查：

```bash
uv run xcore-controller status http://127.0.0.1:9012
uv run xcore-controller command http://127.0.0.1:9012 pose
```

`pose` 返回实测关节、vendor FK 的 `pose10`、控制器法兰位姿和两者平移差；
当前 TCP 是法兰（identity toolset），**不是**已验证的夹爪 TCP。
`prepare`、`arm`、`exit` 都会引起真实运动，只有在现场确认安全后执行；
`arm` 前需保持 GELLO 静止并满足对齐门限。运动中断流会锁定并停止跟随，
重新握手不会自动 arm。

## 远端 raw 会话（2026-10-22 阶段 3）

远端运动角色同时提供会话／episode 接口。**只有已 armed 的跟随会话才能开始记录**；
记录线程按 `recording.raw_fps` 从运动 worker 取最新实测样本，再从两台相机的
无损记录分支取满足时间顺序的最近帧，写入 `xcore_ee10_rgbd_v1` raw：

- `state`/`action`：同一 vendor FK 模型得到的法兰 pose10（动作是软限位后的接受目标）；
- 两路 RGB PNG＋两路 uint16 Z16，逐帧帧号、SDK 时间戳和远端接收时间；
- `wrench` 12 维占位、`wrench_valid=[false,false]`；夹爪闭合度暂为 0，均不冒充实测。

```bash
# 先按上一节启动 GELLO、远端运动和 bridge，并 arm（真实运动，需现场确认）。
uv run xcore-controller command http://127.0.0.1:9012 session/start --task "pick and place"
uv run xcore-controller command http://127.0.0.1:9012 episode/start
uv run xcore-controller command http://127.0.0.1:9012 episode/save
# 或 episode/discard --reason "misaligned"; 结束时 session/stop
```

HTTP 接口（经本地 bridge 或直接调用）：

| 接口 | 行为 |
| --- | --- |
| `/session/start` `{"task": "..."}` | 新建 `raw/<session>/session.json` |
| `/episode/start` | 要求已 armed；启动两台相机无损记录并开始写 raw |
| `/episode/save` | 停止相机记录、校验完整、写 `COMMITTED.json` |
| `/episode/discard` | 标记丢弃，保留 `.partial` 和 `DISCARDED.json` |
| `/session/stop` | 关闭没有活动 episode 的会话 |

相机失败、队列丢帧、FK 缺失、样本或图像超时都会使该 episode 失败；失败后
`save` 拒绝提交，只能丢弃。raw 目录默认 `$HOME/project/xcore-data/raw`。

## 远端转换队列与拉取（2026-10-22 阶段 4）

`session/stop` 默认把已封存会话排入远端转换队列并在后台执行（`recording.convert`）。
转换在独立 Python 3.12 数据环境运行，使用 LeRobot 0.6，输出到
`~/project/xcore-data/lerobot/<dataset_id>/rev-XXXX`；任务状态在
`~/project/xcore-data/jobs/`，失败保留 staging 供排查和重试。

```bash
# 远端队列（经 SSH 手动查看／重试）
ssh rokae@192.168.2.225 'cd ~/project/xcore-dataset && \
  ~/project/xcore-runtime/dataset-venv/bin/python -m xcore_dataset.cli jobs \
  --root ~/project/xcore-data'

# 本地按需拉取完整已发布 revision（rsync + SHA-256 + loader 回读）
./scripts/pull_dataset.sh <dataset_id> <rev-0001>
```

一个 session 生成一个 LeRobot 数据集：每个已提交 raw episode 对应一个 LeRobot
episode，质量报告逐 episode 保存帧数、时间误差和来源 SHA-256。转换崩溃后
`running` 任务会自动重新排队，staging 改名保留，已发布 revision 不被覆盖。
2026-10-22 已用远端两 episode 合成会话完成 publish → LeLab／API 读取 →
本地 `pull_dataset.sh` 校验和 loader 回读（8 帧、2 episodes）。

## 完整数采流程（2026-10-26 更新）

前置：远端已部署 controller 硬件角色（`xcore-controller-hardware.service`，
disabled，按需启动）、相机服务、3.12 数据环境；本地已安装 controller 环境。
首次或升级后同步源码／现场标定，不要用 `submodule update --remote` 替换固定版本。
远端首次安装缺失的 unit（在远端 `~/project/xcore-controller` 执行，需先确认现场部署）：

```bash
# 远端系统 python3 为 3.10，安装脚本需要 3.11 读取 TOML：
~/project/xcore-runtime/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11 \
  deploy/install_role_services.py --add-missing
```

该脚本只补缺失 unit（disabled），不会覆盖已有 unit 或启动硬件。

日常从服务全部停止的状态进入数采，只需一个命令：

```bash
./scripts/start_remote_record.sh --task "pick and place" --enable-motion
```

入口会按需启动／检查远端控制器 API、夹爪 API、本地 GELLO、两台 RGBD 相机、
LeLab 和相应 SSH 连接。已运行的服务会检查后复用；本地 controller 环境缺失时
会由 uv 准备 Python 3.11 环境。输入一次 `y`，才会进行必要的夹爪激活、两臂对齐和
arm；成功后 R 开始、S 保存、D 丢弃、Q 退出。首次远端部署、SSH 密钥、网线／USB
连接和现场标定须已完成，入口不会自动生成标定或覆盖现场配置。

只启动并检查环境，不启用运动：

```bash
./scripts/start_remote_record.sh --check-only
```

启动进度和相机／LeLab 网址会直接打印，详细日志保存在本次 `logs/remote-record-*`。
退出会清理本次创建的本地 GELLO、controller／LeLab 连接及数据桥；远端按需服务和
相机预览连接保持待命，可用现有 `stop_*` 脚本完全停止。预先手动启动的本地服务会保留。

<details>
<summary>手动分步调试（可使用 --no-auto-start）</summary>

```bash
# 0. 远端夹爪 API（只启动服务和读状态）
./scripts/start_gripper.sh
# 若提示 not activated：夹爪断电后须先确认周围安全，再显式激活一次：
uv run --project xcore-gripper-2F85 gripper activate --host 192.168.2.225 --port 5005
# 已激活时无需重复激活；再次检查就绪状态：
./scripts/start_gripper.sh --status
# 1. 远端双相机 API 与采集（不启动运动）
./scripts/start_camera.sh --no-open
# 2. 本地只读 GELLO 服务（占本地跟随锁）
./scripts/start_gello_service.sh
# 3. 远端 SDK owner（只连接和读反馈，不运动）
./scripts/start_remote_controller.sh --hardware
# 4. 数采：先确认现场安全，脚本会 prepare→arm，然后 R 开始／S 保存／D 丢弃／Q 退出
./scripts/start_remote_record.sh --task "pick and place" --enable-motion --no-auto-start
#    或旧入口转发：./scripts/start_data_record.sh --remote --task "…" --enable-motion
# 5. 会话结束时自动排队转换；也可手动查看／重试
./scripts/convert_dataset.sh --list
./scripts/convert_dataset.sh <session_id>
./scripts/convert_dataset.sh --retry <job_id>
# 6. 本地按需拉取完整已发布 revision
./scripts/pull_dataset.sh <dataset_id> <rev-0001>
# 7. 结束：退出脚本会按 return_mode 返回；然后停止远端服务
./scripts/stop_remote_controller.sh
./scripts/stop_dataset.sh
./scripts/start_camera.sh stop
```

</details>

终端模式 `start_remote_record.sh --enable-motion` 在一次 `y` 确认后激活夹爪、机械臂并
创建会话；网页模式只准备组件，点击网页“启动跟随”后才激活、prepare、arm 和创建会话。
正常 `Q`、Ctrl+C、关闭网页或故障退出都会：丢弃未保存片段、停止会话、
按 `return_mode` 返回（`none` 不返回）、机械臂下电，并停止本次启动的远端
controller／相机／夹爪／LeLab 服务；`--keep-services` 可保留服务。
关闭前会等待后台转换完成（`timeouts.conversion_wait_s`），避免停服务中断转换。
`--check-only` 只检查服务，不激活、不停服务。

`arm` 会等待 RT 回调实际推进和新鲜夹爪反馈，成功后才显示就绪并创建会话。
脚本每秒检查两次远端跟随状态；六轴／夹爪出错或 bridge 退出时会直接显示原因、
停止会话并返回失败，**故障退出不自动返回姿态**。正常 Q 仍按 return_mode 执行。
空会话不触发转换。启动就绪超时由远端 `robot.arm_timeout_s` 配置（默认 20 秒）。

远端 `robot.follow_gripper=true` 默认在显式 arm 后同时启动六轴和夹爪跟随，
ID7 扳机的开／合角度、夹爪速度／力和 raw 开／合位置使用 SDK 配置中的 `[gripper]`。
启动数据记录前会检查夹爪服务，未激活则在 prepare 前拒绝，不会边动六轴边忽略夹爪故障。
state 第 10 维来自夹爪实测反馈，action 第 10 维来自扳机目标；反馈异常或过期会停止跟随。
仅六轴实验可在远端配置中显式设 `robot.follow_gripper=false` 并重启 controller，
此时元数据会明确标记夹爪关闭及零占位。

S 保存会停止该片段的录制、等待图像落盘并封存；主臂数据桥继续运行，六轴和夹爪
继续跟随。看到 `committed: true` 表明该片段已封存，完整会话在 Q 后进入转换队列。
按 S 会立即显示“正在保存”，完成后显示“保存完成”；帧数较多时校验／落盘需等待，
无需反复按 S。按键无需回车；保存期间重复的 S/D 会忽略，R 最多排队一次作为下一段
开始请求，Q 会在当前保存完成后退出。退出时会恢复终端原来的回显和输入模式。

2026-10-26 已在现场完成两轮当前姿态保持的 RT 启停、夹爪约 10 raw 单位的小幅动作，
并封存 31 行真实双 RGBD 验收数据；保存期间主臂数据继续推进。验收不包含六轴大幅轨迹，
未执行 prepare 或回零。该数据任务标记为 VALIDATION ONLY，不能当作训练示范。

## 网页数采面板（2026-10-26）

在同一数采入口加 `--web` 即可启动本地 loopback 面板（默认
`http://127.0.0.1:8095`，端口见 `[web].port`）：

```bash
# 只读查看：能看状态和两路 RGBD，不能启动跟随
./scripts/start_remote_record.sh --task "pick and place" --web
# 允许运动：页面仍需勾选安全确认，后端再校验一次性确认令牌
./scripts/start_remote_record.sh --task "pick and place" --web --enable-motion
```

页面提供任务填写、启动/停止跟随、开始记录、保存、丢弃、结束会话，显示运动/夹爪/
记录/转换状态和两台相机的 RGB、深度实时预览。长操作在一个后台任务中执行，页面轮询
真实远端状态；重复点击会被拒绝。

点击“结束会话”后，面板会等待本次会话在远端完成转换、完整性校验和发布，期间锁定
采集操作；显示“数据集已保存并发布”后才允许开始下一轮。刷新页面仍会检查远端转换
状态，命令排队成功不等于数据已保存完成；转换失败会明确显示原因。

网页模式加 `--enable-motion` 只允许网页运动按钮，不会在打开页面前激活夹爪、
`prepare`、`arm` 或创建会话。确认现场安全后，在网页勾选确认并点击“启动跟随”，
才执行这些动作。未开始跟随就关闭页面时不执行返回动作。关闭页面（或浏览器崩溃）
会在 `[web].close_grace_s`／`heartbeat_timeout_s` 后执行同一套完全关闭流程；刷新
页面会在宽限内重新心跳并取消关闭。网页与 CLI 共用数采入口锁和远端会话互斥。
LeLab 提供浏览、受控删除已发布版本，以及通过独立“Pull 到本地”链接拉取数据；
不开放 Hugging Face 上传、合并、训练或运动接口。

## 拉取末端或关节表示（2026-10-26）

```bash
./scripts/pull_dataset.sh --list
./scripts/pull_dataset.sh --pose DATASET_ID REVISION
./scripts/pull_dataset.sh --joints DATASET_ID REVISION
```

`--pose` 拉取 pose10（xyz、旋转矩阵前两列、夹爪闭合度），`--joints` 拉取
`[q1..q6,g]`（rad＋闭合度）。两者都保留双 RGBD、12 维力/掩码、任务和时间元数据。
远端转换时关节数据**从 raw 的 joints_rad/target_rad 构建**，不会对 pose10 做 IK；
旧数据缺少关节字段会明确拒绝。关节转换默认发布为 `<session>-joints`，因此不会与
pose10 版本互相覆盖；`--list` 会显示每个版本的 representation。拉取后先校验
`representation.json`（旧 EE10 版本按特征维度推断），不匹配时保留 partial 供排查，
不会发布成正式目录。旧命令 `pull_dataset.sh ID REVISION` 仍按 pose10 完整包行为工作。

### 通过 LeLab 按钮拉取

```bash
./scripts/start_dataset.sh
# 浏览器打开 http://127.0.0.1:8090/edit-dataset
```

在数据集查看页右上角，点击与 Merge／Upload 同样式的“Pull 到本地”按钮，会打开统一的
`/upload` 页面，并自动选中当前版本。在页面选择 `--pose`（末端 10 维）或 `--joints`
（关节＋夹爪 7 维，rad）。若当前版本不是所选表示，
系统会核验其 raw 来源并在远端生成对应格式，再传回本地；缺少关节字段或来源不一致
会报错，不会做 IK 或改写原数据。按需生成的版本用来源摘要命名，重复选择会复用。

完成 SHA-256 校验及 LeRobot 回读后，页面显示本地绝对路径并可复制，默认位于
`data/lerobot/<dataset_id>/<revision>/`。此时“开始拉取”会变成“打开路径”，
点击后由本机网关用 `xdg-open`（回退 `gio open`）打开该文件夹——浏览器不能直接跳转
`file://`，所以这一步在网关进程里执行，且只允许打开本地数据集根目录下的已存在目录。本地使用 `.partial` 断点续传，正式版本不覆盖。
保持 `start_dataset.sh` 进程运行以完成任务；原保存、停止及自动转换行为不变。
命令行 `pull_dataset.sh --pose/--joints` 仍校验并拉取指定已发布表示；按需切换格式是
本次新增的网页功能。

浏览地址仍为 8090，已由本地网关提供；内部 SSH 隧道改用 8091（可配置）。升级前若有
旧的 `start_dataset.sh` 隧道占用 8090，先在旧终端 Ctrl+C，再运行新的入口。

直接打开 `http://127.0.0.1:8090/upload` 也会进入本地拉取页面，可选择远端数据集和
pose/joints 格式；不会进入原 Hugging Face 上传流程。已有浏览器标签页升级后应完整刷新，
以加载新的页面脚本。复用本地网关启动数采时会再次确认并按需启动远端数据服务，
防止上次退出停止远端 LeLab 后，本地仍存活的网关返回 502。浏览期间上游断开时，
网关也会按需恢复仅数据浏览服务并重试读取；不启动硬件，写操作不会自动重放。

“Pull 到本地”按钮由页面脚本注入到数据集查看页的 Merge／Upload 旁边，并直接复用
Upload 的样式类，因此与它们外观一致；离开查看页或没有选中版本时会自动移除。
升级后应先完整刷新最初打开的 LeLab 首页一次。
