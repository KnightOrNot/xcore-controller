# xcore-controller：GELLO → CR7 六轴与夹爪跟随

本指南从 **Ubuntu 24.04、x86_64 的空白控制电脑**开始，完成安装、通信、标定和真机跟随。
统一客户端读取一次 GELLO，将六轴目标发给 CR7，将扳机目标发给独立 Robotiq 2F-85 服务。
CR7 保持六轴接口。首次完成以下步骤后，每次实验使用文末的[日常启动命令](#8-日常启动)。

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
./setup.sh --skip-submodules
./setup.sh --check-only
./xcore-sdk-python/.venv/bin/xcore-sdk-python doctor
```

如仓库需要访问权限，使用有权限的 GitHub 凭据；已配置 GitHub SSH 的用户也可直接运行
`./setup.sh`，让脚本初始化子模块。跟随使用 PyPI 的 `dynamixel-sdk`，
无需额外安装 `third_party/DynamixelSDK/python`，也无需初始化仿真模型的嵌套子模块。

`setup.sh` 安装四个独立环境，包括数据转换依赖，不连接硬件。
最后应显示“四个子项目的环境与命令入口检查通过”；`doctor` 应返回 `ok: true`、
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
./start_gripper.sh
./start_gripper.sh --status
```

预期打印“远端夹爪服务已就绪”，有 `streaming: true`、`stream_error: null` 和实际 `position_raw`。
已有服务不会重启。如果上次退出留下单纯的“目标断流超时”，入口会在取得跟随锁、
确认没有跟随／回零任务后自动发送 `stop` 清除锁定，再检查反馈；不重新激活或开爪。
`--status` 始终只读。串口、电源等其他故障仍会报错，不自动清除。
新系统显示“Unit ... not found”时继续执行 5.2。

### 5.2 新夹爪服务电脑：首次部署

这一节安装支持连续跟随的服务，供顶层 `start_gripper.sh` 管理。
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
systemctl --user enable --now xcore-gripper-follow.service
systemctl --user status xcore-gripper-follow.service --no-pager
journalctl --user -u xcore-gripper-follow.service -n 30 --no-pager
exit
```

远端应为 `active (running)`，日志显示监听 `0.0.0.0:5005`。
这是监听地址，控制电脑仍连接 `192.168.2.225:5005`。
用户服务默认随账户登录运行；需要未登录也持续运行时，在远端执行
`sudo loginctl enable-linger "$USER"`。防火墙已启用且阻断连接时，在远端允许控制电脑访问：
`sudo ufw allow from 192.168.2.100 to any port 5005 proto tcp`。

回到**控制电脑**检查：

```bash
./start_gripper.sh
./start_gripper.sh --status
```

如果夹爪 USB 实际接在控制电脑，改在一个独立终端运行本机服务并保持终端打开：

```bash
./start_gripper.sh --local \
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
./start_gello_follow.sh --enable-motion --calibrate-zero
```

输入 `y` 后，脚本把 CR7 六轴移动至 0°，采集 GELLO 偏移并保存标定，随后直接进入六轴与夹爪跟随。
**这条命令会真实运动**；不能将任意主臂姿态当作标准零位。
标定成功后按 Ctrl+C 结束，再按第 7 节检查方向并实验。只标定六轴时可加 `--arm-only`。

已有文件不会覆盖。需要重新标定时指定新文件，并在后续启动中使用同一个路径：

```bash
./start_gello_follow.sh --enable-motion --calibrate-zero \
  --calib ./xcore-sdk-python/config/cr7_calib_new.json
# 后续启动
./start_gello_follow.sh --enable-motion \
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
./start_gello_follow.sh --show-state
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
./start_gello_follow.sh --enable-motion
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
./start_gello_follow.sh --enable-motion --max-speed-deg 10 --prepare-speed 50
# 已确认现场范围后，按需要调节实时速度与对齐速度
./start_gello_follow.sh --enable-motion --max-speed-deg 30 --prepare-speed 1000
```

每次换参数先 Ctrl+C 结束上一次跟随。命令行优先于环境变量，再优先于脚本默认值。
`XCORE_FOLLOW_MAX_SPEED_DEG`、`XCORE_PREPARE_SPEED` 可设置速度；也可修改顶层脚本开头的默认值。
夹爪端点、速度和力度都可通过表中参数覆盖，例如：

```bash
./start_gello_follow.sh --enable-motion \
  --gripper-open-deg 194.8 --gripper-close-deg 153 \
  --gripper-open-pos 0 --gripper-closed-pos 230 --gripper-speed 150 --gripper-force 30
```

仅测试六轴时运行 `./start_gello_follow.sh --enable-motion --arm-only`，无需夹爪服务。
`--arm-only` 不能与 `--gripper-host` 同用。
默认只输出启动、错误及停止信息，需要连续状态时加 `--show-state`。

**结束实验：按 Ctrl+C，等待六轴回到零位后退出。** 脚本先停止跟随和夹爪，
关闭实时／准备 SDK 会话，再将六轴移到 `[0°, 0°, 0°, 0°, 0°, 0°]`。
回零沿用 `--prepare-speed`（默认 `4000 mm/s`）和 `--prepare-motion-timeout`
（默认 `600 s`），完成后恢复回零前的电源状态和模式，夹爪保持停止、不自动开爪。
开始实验前也要确认回零路径可用；回零期间再次 Ctrl+C 会请求停止回零并等待 SDK 关闭。
只读预览和故障退出不执行回零。不要在跟随或回零期间另开 SDK 查询／控制会话。
仅希望停止并保持当前姿态时，启动命令加 `--no-return-zero`：

```bash
./start_gello_follow.sh --enable-motion --no-return-zero
./start_data_record.sh --task "pick up the object" --no-return-zero
```
紧急情况使用设备硬件急停；终端退出不能替代硬件急停。

## 8. 日常启动

安装、网络和标定完成后，每次在控制电脑执行以下流程即可。
按实际设备设置 `XCORE_GELLO_PORT`；使用新标定文件时给预览和跟随均添加 `--calib`。

```bash
cd "$HOME/projects/xcore/xcore-controller"
export XCORE_GELLO_PORT=/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0

# 1. 启动并检查远端夹爪服务；已有服务不重启
./start_gripper.sh

# 2. 可选：只读查看六轴／扳机；结束后按 Ctrl+C
./start_gello_follow.sh --show-state

# 3. 主臂保持期望姿态；输入 y，等待对齐完成再移动主臂
./start_gello_follow.sh --enable-motion
# 实验结束按 Ctrl+C，等待从臂六轴回零并退出
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
| `Gripper target stream timed out` | 等跟随／回零退出，再执行 `./start_gripper.sh` 自动清除超时锁定；`--status` 仅查看，`--reset-stream` 可手动清除 |
| 对齐失败／主臂移动／超限 | 保持主臂静止，核对标定、目标和示教器；准备每轴最大跨度 180°，到位等待 600 s；失败后检查实际姿态再重试 |
| “已有跟随启动流程正在运行” | 结束上一跟随／记录进程，等待退出；不要同时启动两个入口 |

夹爪故障排查命令（在控制电脑执行）：

```bash
./start_gripper.sh --status
ssh rokae@192.168.2.225 'systemctl --user status xcore-gripper-follow.service --no-pager'
ssh rokae@192.168.2.225 'journalctl --user -u xcore-gripper-follow.service -n 50 --no-pager'
# 先结束跟随；需要重启时执行（重启会激活夹爪）
./start_gripper.sh --restart
```

跟随日志在 `xcore-sdk-python/logs/follow-*/`：`preparation.json` 是对齐结果，
`server.log` 是服务端日志。六轴跟随已实测；默认高速度对齐和夹爪全行程跟随仍需按现场逐项验收。

## 10. 更新与数据记录

更新到控制器固定的子模块版本，结束实验后执行；不用 `submodule update --remote`：

```bash
git pull --ff-only
git submodule sync
git -c url."https://github.com/".insteadOf=git@github.com: submodule update --init
./setup.sh --skip-submodules
./setup.sh --check-only
```

远端夹爪部署目录独立于本机子模块；本机更新不会自动更新远端服务。

需要记录从臂反馈时，使用记录入口代替普通跟随入口：

```bash
./start_gripper.sh
./start_data_record.sh --task "pick up the object"
```

它先对齐再跟随；R 开始记录、S 保存、D 丢弃、P 查看状态、H 帮助。
Ctrl+C 后先停止跟随、完成六轴回零，再自动转换已保存片段；回零动作不写入 episode。
未保存片段保留为 `.partial`。原始数据在 `data/raw/`，LeRobot 数据在 `data/lerobot/`。

工程细节与原 README 内容见 [docs/DEVELOPMET.md](docs/DEVELOPMET.md)；
扩展说明见 [数据记录](docs/DATA_RECORDING.md)、[现场夹爪服务管理](docs/GRIPPER_SERVER_UPDATE.md)。
