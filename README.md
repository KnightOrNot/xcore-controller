# xcore-controller：xMate CR7 与 GELLO 跟随

当前使用 Python SDK 控制六轴 CR7，并通过一个 shell 脚本启动主臂跟随。顶层仓库组合三个独立子模块，各自维护 Python 环境；工程组织参考 agilex-controller。

## 项目结构与初始化

```text
xcore-controller/
├── xcore-sdk-python/       # submodule：CR7 SDK、ZMQ 服务与六轴跟随
├── xcore-gello-software/   # submodule：GELLO 主臂读取与仿真
├── xcore-gripper-2F85/     # submodule：Robotiq 2F-85 TCP 服务与客户端
├── setup.sh               # 初始化子模块和独立 Python 环境
├── start_gello_follow.sh  # CR7 跟随入口
└── start_gripper.sh       # 夹爪服务器入口
```

```bash
git clone git@github.com:KnightOrNot/xcore-controller.git
cd xcore-controller
./setup.sh
./setup.sh --check-only
```

需预先安装 git、pyenv、uv 和 Python 3.11（例如 `pyenv install -s 3.11.16`）。
SDK 与夹爪使用各自的 `uv.lock`；GELLO 保留原有 `requirements.txt` 安装方式。
厂商 SDK 二进制需按 [SDK 安装说明](xcore-sdk-python/docs/README.md) 安装到 SDK 子模块。
本机使用 CPython 3.11 对应的 Linux 扩展；二进制和现场标定文件不纳入 Git。
`setup.sh` 不访问串口或连接机械臂。

| 项目 | Python 包 | 主命令 |
| --- | --- | --- |
| xcore-sdk-python | `xcore_sdk_python` | `xcore-sdk-python` |
| xcore-gello-software | `xcore_gello_software` | `xcore-gello-software` |
| xcore-gripper-2F85 | `xcore_gripper_2f85` | `xcore-gripper-2f85`、`xcore-gripper-2f85-server` |

## 首次安装与标定

```bash
cd /home/knight/projects/xcore/xcore-controller/xcore-sdk-python
uv sync --frozen --python 3.11
uv run xcore-sdk-python doctor
uv run xcore-sdk-python status --ip 192.168.2.160
```

本机需要匹配 CPython 3.11 的厂商二进制。电脑有线网卡须已配置 `192.168.2.100/24`；换电脑时按实际地址修改配置。完整安装与网络说明见 [SDK 快速启动](xcore-sdk-python/README.md)。

将 GELLO 与 CR7 摆到相同关节姿态并保持不动，生成本机标定文件（只采样，不发运动目标）：

```bash
uv run xcore-sdk-python follow-calibrate --ref-current \
  --serial /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0 \
  --save config/cr7_calib.json
```

单姿态标定只求零位偏移；方向需通过 `--signs` 指定并逐轴预览核对。串口路径按实际设备修改，已有标定文件不会被覆盖。

## 一个脚本启动跟随

回到控制器目录：

```bash
cd /home/knight/projects/xcore/xcore-controller
# 只读预览：显示主臂目标和 CR7 反馈，不发送运动目标
./start_gello_follow.sh

# 核对映射与初始姿态后，启用实际跟随；启动时有交互确认
./start_gello_follow.sh --enable-motion
```

可通过参数覆盖现场配置：

```bash
./start_gello_follow.sh --enable-motion \
  --ip 192.168.2.160 --local-ip 192.168.2.100 \
  --gello-port /dev/ttyUSB0 --calib ./xcore-sdk-python/config/cr7_calib.json \
  --max-speed-deg 3
```

脚本检查依赖、标定与串口，持有单实例锁，启动独占 SDK 会话的服务端，等待就绪后启动主臂客户端。按 Ctrl+C 时先停客户端，再停止服务端并执行 RT 退出流程；日志保存在 `xcore-sdk-python/logs/follow-*/server.log`。启动不会自动移动到主臂姿态，初始误差超过对齐阈值时拒绝跟随。

脚本实现位于 SDK 仓库的 [scripts/start_gello_follow.sh](xcore-sdk-python/scripts/start_gello_follow.sh)，本目录的同名脚本是便捷入口。仅克隆 SDK 仓库时，可直接运行 `./scripts/start_gello_follow.sh`。各操作也保留 `uv run xcore-sdk-python [指令] [参数]` 接口。

本流程覆盖六轴关节跟随；夹爪联动和仿真显示未接入。原生 SDK／非实时运动已有实机记录，新的实时跟随已完成离线测试，尚未在当前 Python 3.11 + SDK 0.7.1 组合下完成真机启停与连续跟随验收。

- [命令与快速启动](xcore-sdk-python/README.md)
- [工程搭建、模块职责与验证边界](xcore-sdk-python/docs/DEVELOPMENT.md)
- [历史 CR7／ROS2 仿真调研](docs/CR7_RESEARCH.md)


## 夹爪服务与 GELLO 仿真

在连接夹爪 USB/RS485 的电脑启动夹爪服务：

```bash
./start_gripper.sh --serial-port /dev/ttyUSB0
```

查看各子项目的独立命令：

```bash
./xcore-sdk-python/.venv/bin/xcore-sdk-python --help
./xcore-gello-software/.venv/bin/xcore-gello-software --help
./xcore-gripper-2F85/.venv/bin/xcore-gripper-2f85 --help
```

GELLO 仿真与原来的实验脚本均可使用；CR7 仿真需先准备
`xcore-gello-software/third_party/cr7/cr7_scene.xml` 及其模型资源，详见子项目文档。

## 子模块维护

拉取控制器固定版本：

```bash
git pull --ff-only
git submodule sync
git submodule update --init
```

子项目修改应先在对应仓库测试、提交并推送，再提交控制器的子模块指针。例如：

```bash
git -C xcore-sdk-python switch main
git -C xcore-sdk-python pull --ff-only
git add xcore-sdk-python
git commit -m "chore: update xcore-sdk-python submodule"
git push origin main
```

GELLO 和夹爪项目使用相同流程。子模块可能处于 detached HEAD，这是按提交固定版本的正常状态。
