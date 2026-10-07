# xCore / xMate CR7 控制与 GELLO 跟随

当前使用 Python SDK 控制六轴 CR7，并通过一个 shell 脚本启动主臂跟随。工程组织参考 `../agilex/agilex-controller` 的启动流程及 `agilexrobotics` 的 CLI／驱动划分；CR7 SDK 接口和实时关节控制参考 `../gello for CR7`。

## 首次安装与标定

```bash
cd /home/knight/projects/xcore/xcoresdk-python
uv sync --frozen --python 3.11
uv run xcore doctor
uv run xcore status --ip 192.168.2.160
```

本机需要匹配 CPython 3.11 的厂商二进制。电脑有线网卡须已配置 `192.168.2.100/24`；换电脑时按实际地址修改配置。完整安装与网络说明见 [SDK 快速启动](xcoresdk-python/README.md)。

将 GELLO 与 CR7 摆到相同关节姿态并保持不动，生成本机标定文件（只采样，不发运动目标）：

```bash
uv run xcore follow-calibrate --ref-current \
  --serial /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0 \
  --save config/cr7_calib.json
```

单姿态标定只求零位偏移；方向需通过 `--signs` 指定并逐轴预览核对。串口路径按实际设备修改，已有标定文件不会被覆盖。

## 一个脚本启动跟随

回到当前工作区根目录：

```bash
cd /home/knight/projects/xcore
# 只读预览：显示主臂目标和 CR7 反馈，不发送运动目标
./start_gello_follow.sh

# 核对映射与初始姿态后，启用实际跟随；启动时有交互确认
./start_gello_follow.sh --enable-motion
```

可通过参数覆盖现场配置：

```bash
./start_gello_follow.sh --enable-motion \
  --ip 192.168.2.160 --local-ip 192.168.2.100 \
  --gello-port /dev/ttyUSB0 --calib ./xcoresdk-python/config/cr7_calib.json \
  --max-speed-deg 3
```

脚本检查依赖、标定与串口，持有单实例锁，启动独占 SDK 会话的服务端，等待就绪后启动主臂客户端。按 Ctrl+C 时先停客户端，再停止服务端并执行 RT 退出流程；日志保存在 `xcoresdk-python/logs/follow-*/server.log`。启动不会自动移动到主臂姿态，初始误差超过对齐阈值时拒绝跟随。

脚本实现位于 SDK 仓库的 [scripts/start_gello_follow.sh](xcoresdk-python/scripts/start_gello_follow.sh)，本目录的同名脚本是便捷入口。仅克隆 SDK 仓库时，可直接运行 `./scripts/start_gello_follow.sh`。各操作也保留 `uv run xcore [指令] [参数]` 接口。

本流程覆盖六轴关节跟随；夹爪联动和仿真显示未接入。原生 SDK／非实时运动已有实机记录，新的实时跟随已完成离线测试，尚未在当前 Python 3.11 + SDK 0.7.1 组合下完成真机启停与连续跟随验收。

- [命令与快速启动](xcoresdk-python/README.md)
- [工程搭建、模块职责与验证边界](xcoresdk-python/docs/DEVELOPMENT.md)
- [历史 CR7／ROS2 仿真调研](docs/CR7_RESEARCH.md)
