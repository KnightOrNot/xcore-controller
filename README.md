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

## 只用 sh 命令启动跟随

在控制器目录运行。电脑通过 WiFi 联网，有线网卡使用 `192.168.2.100/24`
直连 CR7 的 `192.168.2.160`，有线连接不设置默认网关或 DNS。

```bash
cd /home/knight/projects/xcore/xcore-controller
# 首次安装环境；已有环境可只检查
./setup.sh
./setup.sh --check-only

# 只读预览，核对主臂目标与从臂反馈
./start_gello_follow.sh

# 正常启动：低速移动从臂到 GELLO 当前姿态，然后进入跟随
./start_gello_follow.sh --enable-motion
```

本机已在 2026-10-08 保存 `xcore-sdk-python/config/cr7_calib.json`，可以直接使用
最后一条命令。**启动前保持 GELLO 在期望姿态，准备对齐期间保持主臂不动。**
输入 `y` 确认后，脚本读取主臂、应用现场零位偏移和轴方向，选择与从臂当前
关节角最近的 2π 分支，再以 `MoveAbsJ` 低速移动到这个目标。到位并检查主臂
未移动后，关闭准备 SDK 会话，启动独占的实时服务和 GELLO 客户端。
正常启动直接对齐当前目标，不要求主臂在零位，也不先回零或重新标定。

准备速度默认 `50 mm/s`（SDK 速度参数），每轴角度差上限 `180°`，
每段运动到位等待默认 `600 s`，到位容差 `0.2°`。实时跟随速度上限另为 `3°/s`。
确认的是实际运动路径和范围；关节软限位不能判断周围障碍物。

### 新电脑或首次零位标定

现场标定文件不纳入 Git。缺少标定时，将 **GELLO 六轴摆到对应 CR7 六轴均为
0° 的标准零位**，保持不动，再执行：

```bash
./start_gello_follow.sh --enable-motion --calibrate-zero
```

这条命令先低速将 CR7 六轴移动到 `0°`，核对实际到位反馈，再采集 GELLO
零位偏移并保存标定，随后进入跟随。仅首次标定走归零流程；不能把任意 GELLO
姿态当作零位。已有标定不会被覆盖；需要重标定时指定新文件，并在后续启动中
继续指定该文件：

```bash
./start_gello_follow.sh --enable-motion --calibrate-zero \
  --calib ./xcore-sdk-python/config/cr7_calib_new.json
./start_gello_follow.sh --enable-motion \
  --calib ./xcore-sdk-python/config/cr7_calib_new.json
```

单姿态标定只确定零位偏移，首次默认沿用本机六轴方向 `[1,1,1,1,1,1]`。
轴方向需按现场逐轴核对；不同装配请使用 SDK 的同姿态标定命令指定 `--signs`。

### 启动参数与停止

可通过参数覆盖现场配置：

```bash
./start_gello_follow.sh --enable-motion \
  --ip 192.168.2.160 --local-ip 192.168.2.100 \
  --gello-port /dev/ttyUSB0 --calib ./xcore-sdk-python/config/cr7_calib.json \
  --max-speed-deg 3 --prepare-speed 50 --prepare-motion-timeout 600
```

脚本持有同一把单实例锁，准备、实时跟随和记录不会重叠占用 SDK 或 GELLO。
已手动对齐时，可用 `./start_gello_follow.sh --enable-motion --skip-prepare` 跳过准备
移动，仍保留启动对齐闸门。`--yes` 可跳过交互确认。参数错误、超限目标、
准备期间主臂移动或准备失败都会阻止实时跟随启动。

按 **Ctrl+C** 停止。准备阶段会请求停止，等机器人空闲后恢复准备前的电源和模式；
跟随阶段先停 GELLO 客户端，再关闭实时 SDK 会话，恢复 NRT／manual，
不自动下电或归零。不要在跟随运行中再次启动脚本或另开 SDK 查询/运动命令。
日志位于 `xcore-sdk-python/logs/follow-*/`：`preparation.json` 保存到位结果，
`server.log` 保存实时跟随日志。

脚本实现位于 SDK 仓库的 [scripts/start_gello_follow.sh](xcore-sdk-python/scripts/start_gello_follow.sh)，本目录的同名脚本是便捷入口。仅克隆 SDK 仓库时，可直接运行 `./scripts/start_gello_follow.sh`。各操作也保留 `uv run xcore-sdk-python [指令] [参数]` 接口。

本流程默认覆盖六轴关节跟随；指定 `--gripper-host` 可同时跟随独立外接夹爪，见下方。
2026-10-08 已完成 CR7 六轴归零、现场标定及实时跟随实测，用户确认能正常跟随。
新增启动对齐流程有离线覆盖；独立夹爪联动和数采仍需单独完成真机验收。

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

# 按已有标定自动对齐初始姿态，再六轴与夹爪同时跟随
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
`start_gello_follow.sh` 或其他 GELLO 读取进程；启动时按已有标定先低速对齐到
主臂当前目标，再跟随和记录。记录入口也支持 `--prepare-*`、`--skip-prepare`
和首次 `--calibrate-zero` 参数。

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
