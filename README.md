# xcore-controller：xMate CR7 与 GELLO 跟随

当前使用 Python SDK 控制六轴 CR7，独立控制 Robotiq 夹爪，并提供统一跟随、数据记录和 LeRobot 转换入口。顶层仓库组合四个独立子模块，各自维护 Python 环境；工程组织参考 agilex-controller。

## 项目结构与初始化

```text
xcore-controller/
├── xcore-sdk-python/       # submodule：CR7 SDK、ZMQ 服务与六轴跟随
├── xcore-gello-software/   # submodule：GELLO 主臂读取与仿真
├── xcore-gripper-2F85/     # submodule：Robotiq 2F-85 TCP 服务与客户端
├── lerobot-converter/      # submodule：原有 PiPER-X 转换器，保持原样
├── tools/convert_cr7.py    # 控制器侧 CR7 适配，复用转换器的数据集写入
├── setup.sh               # 初始化子模块和独立 Python 环境
├── start_gello_follow.sh  # CR7 跟随入口
├── start_gripper.sh       # 夹爪服务器入口
└── start_data_record.sh   # 跟随时记录从臂反馈，退出后离线转换
```

```bash
git clone git@github.com:KnightOrNot/xcore-controller.git
cd xcore-controller
./setup.sh
./setup.sh --check-only
```

需预先安装 git、pyenv、uv 和 Python 3.11 / 3.12（例如 `pyenv install -s 3.11.16`、
`pyenv install -s 3.12.14`）。转换器使用独立 Python 3.12，安装锁定的 CPU 数据集依赖。
SDK 与夹爪使用各自的 `uv.lock`；GELLO 保留原有 `requirements.txt` 安装方式。
厂商 SDK 二进制需按 [SDK 安装说明](xcore-sdk-python/docs/README.md) 安装到 SDK 子模块。
本机使用 CPython 3.11 对应的 Linux 扩展；二进制和现场标定文件不纳入 Git。
`setup.sh` 不访问串口或连接机械臂。

| 项目 | Python 包 | 主命令 |
| --- | --- | --- |
| xcore-sdk-python | `xcore_sdk_python` | `xcore-sdk-python` |
| xcore-gello-software | `xcore_gello_software` | `xcore-gello-software` |
| xcore-gripper-2F85 | `xcore_gripper_2f85` | `xcore-gripper-2f85`、`xcore-gripper-2f85-server` |
| lerobot-converter | `lerobot_converter` | `lerobot-converter` |

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

本流程默认覆盖六轴关节跟随；指定 `--gripper-host` 可同时跟随独立外接夹爪，见下方。
原生 SDK／非实时运动已有实机记录；实时跟随及夹爪联动已完成离线测试，尚未完成真机启停与连续跟随验收。

- [命令与快速启动](xcore-sdk-python/README.md)
- [工程搭建、模块职责与验证边界](xcore-sdk-python/docs/DEVELOPMENT.md)
- [历史 CR7／ROS2 仿真调研](docs/CR7_RESEARCH.md)


## 夹爪服务与 GELLO 仿真

在连接夹爪 USB/RS485 的电脑启动夹爪服务：

```bash
./start_gripper.sh --serial-port /dev/ttyUSB0
```

上面的串口必须属于夹爪 RS485 适配器，与 GELLO 串口不同；优先使用实际
`/dev/serial/by-id/...` 路径。夹爪服务启动会激活夹爪。

服务就绪后，在另一终端运行统一跟随入口；同机服务使用 `127.0.0.1`，
异机服务使用夹爪 USB 所在电脑的 IP：

```bash
# 只读预览：不发送机械臂或夹爪运动目标
./start_gello_follow.sh --gripper-host 127.0.0.1

# 对齐初始姿态、核对标定后，六轴与夹爪同时跟随
./start_gello_follow.sh --gripper-host 127.0.0.1 --enable-motion
```

同一客户端每帧读取 GELLO 六轴和 ID 7 扳机，再分别发送到 CR7 六轴服务和夹爪 TCP 服务。
默认六轴 50 Hz、夹爪 5 Hz。夹爪工作线程只发送最新闭合度，不阻塞机械臂目标更新；
服务端允许运动中修改目标。`--gripper-open-deg` / `--gripper-close-deg` 默认
194.8° / 153°，需按实测确认；实际夹爪端点通过 `--gripper-open-pos` /
`--gripper-closed-pos` 设置，速度、力度通过 `--gripper-speed` / `--gripper-force` 设置。

跟随期间仅统一客户端读取 GELLO，不同时启动 `read` 或仿真跟随进程。
Ctrl+C 停止客户端时发送夹爪停止请求，并退出 CR7 跟随；夹爪默认 1.5 s 未收到刷新
会触发服务端停止保护。真实的响应速度和停止效果仍需实机验收。
完整参数与测试边界见 [SDK README](xcore-sdk-python/README.md)。

## 从臂六轴与夹爪数据记录和转换

先启动上面的夹爪服务，再运行记录入口。它包含统一跟随流程，不同时启动普通
`start_gello_follow.sh` 或其他 GELLO 读取进程；启动时仍要求现场标定和姿态对齐。

```bash
./start_data_record.sh --task "pick up the object"
# 自定义夹爪地址、数据集帧率，并在对齐后立即记录第一段
./start_data_record.sh --gripper-host 127.0.0.1 --task "pick object" \
  --dataset-fps 30 --start-recording
```

R 开始 episode，S 保存，D 丢弃，P 查看状态，H 查看帮助。
Ctrl+C 先停止跟随并关闭 SDK 服务，再转换已经保存的 episode。
未保存的 episode 留为 `.jsonl.partial`，不会被当作正式训练数据转换。

```text
data/raw/session_*/manifest.json
data/raw/session_*/episodes/episode_000000.jsonl
data/raw/session_*/episodes/episode_000001.jsonl.partial
data/lerobot/session_*/data/ + meta/ + quality_report.json
```

`action` 为七维请求目标；`observation.state` 为六轴实际 SDK 关节角加实际夹爪
闭合度。记录同时保留两路反馈时间戳、年龄和夹爪原始位置，不用主臂目标替代实测反馈。
夹爪闭合度通过实际位置及夹爪端点标定归一化到 0～1。
CR7 数据不填充不存在的速度或末端位姿 feature。
默认 raw 循环 50 Hz，转换 30 FPS；反馈仍按各自实际刷新率更新，质量报告显示
两路反馈频率和最大年龄。反馈缺失/过期或写盘队列满会停止跟随并保留 `.partial`。

只记录原始数据、稍后手工转换：

```bash
./start_data_record.sh --task "pick object" --skip-conversion
./lerobot-converter/.venv/bin/python tools/convert_cr7.py \
  data/raw/session_YYYYMMDD_HHMMSS data/lerobot/session_YYYYMMDD_HHMMSS \
  --repo-id local/cr7_gello_session_YYYYMMDD_HHMMSS --fps 30
```

可用 `--raw-data-root` / `--lerobot-data-root` 更改目录。
输出目录必须不存在，转换不覆盖旧数据，不上传到 Hugging Face。
`lerobot-converter` 子模块保持原样。CR7 的适配全部位于控制器新增
`tools/convert_cr7.py`，复用其重采样和数据集写入功能；
说明见 [数据记录与转换](docs/DATA_RECORDING.md)。
已完成离线记录/退出测试和真实 LeRobot 数据集写入验证；本机从臂真机采集尚待验收。

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
