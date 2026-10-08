# xcore-controller 开发与现场记录

本文由原项目 README 迁移，保留工程结构、参数解释与现场验证记录。
新系统安装和日常实验以 [快速开始](../README.md) 为准。

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
SDK 子模块已包含本项目使用的 Linux x86_64、CPython 3.11 二进制；其他平台按 [SDK 安装说明](../xcore-sdk-python/docs/README.md) 获取匹配库。
本机使用 CPython 3.11 对应的 Linux 扩展；Linux x86_64、CPython 3.11 的 SDK 0.7.1 二进制已纳入 Git；现场标定文件不纳入 Git。
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

本机需要匹配 CPython 3.11 的厂商二进制。电脑有线网卡须已配置 `192.168.2.100/24`；换电脑时按实际地址修改配置。完整安装与网络说明见 [SDK 快速启动](../xcore-sdk-python/README.md)。

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

# 正常启动：对齐从臂到 GELLO 当前姿态，然后六轴与夹爪同时跟随
./start_gello_follow.sh --enable-motion
```

这两条命令默认启用独立夹爪，需先在夹爪 USB/RS485 所在电脑启动
`./start_gripper.sh --serial-port <夹爪串口>`；详见下方夹爪连接流程。
仅测试六轴时，分别使用 `./start_gello_follow.sh --arm-only` 和
`./start_gello_follow.sh --enable-motion --arm-only`。

本机已在 2026-10-08 保存 `xcore-sdk-python/config/cr7_calib.json`，可以直接使用
最后一条命令。**启动前保持 GELLO 在期望姿态，准备对齐期间保持主臂不动。**
输入 `y` 确认后，脚本读取主臂、应用现场零位偏移和轴方向，选择与从臂当前
关节角最近的 2π 分支，再以 `MoveAbsJ` 移动到这个目标。到位并检查主臂
未移动后，关闭准备 SDK 会话，启动独占的实时服务和 GELLO 客户端。
正常启动直接对齐当前目标，不要求主臂在零位，也不先回零或重新标定。

准备速度默认 `4000 mm/s`（SDK 参数上限），每轴角度差上限 `180°`，
每段运动到位等待默认 `600 s`，到位容差 `0.2°`。实时跟随默认上限为 `75°/s`。
确认的是实际运动路径和范围；关节软限位不能判断周围障碍物。

### 新电脑或首次零位标定

现场标定文件不纳入 Git。缺少标定时，将 **GELLO 六轴摆到对应 CR7 六轴均为
0° 的标准零位**，保持不动，再执行：

```bash
./start_gello_follow.sh --enable-motion --calibrate-zero
```

这条命令先将 CR7 六轴移动到 `0°`，核对实际到位反馈，再采集 GELLO
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
  --max-speed-deg 75 --prepare-speed 4000 --prepare-motion-timeout 600
```

启动对齐速度可以修改顶层脚本的 `prepare_speed="${XCORE_PREPARE_SPEED:-4000}"`，
或使用 `--prepare-speed` 覆盖；也支持环境变量 `XCORE_PREPARE_SPEED`。
这是 `MoveAbsJ` 的 SDK mm/s 参数，不是六个关节各自的 °/s 速度；合法范围
为 5～4000，默认采用参数上限。

调节实时跟随速度时，可以直接修改本目录 `start_gello_follow.sh` 开头的
`max_speed_deg="${XCORE_FOLLOW_MAX_SPEED_DEG:-75}"`，将末尾的 `75` 改成期望的
每轴速度上限（单位 °/s）。也可以每次通过命令指定，例如：

```bash
./start_gello_follow.sh --enable-motion --max-speed-deg 10
./start_gello_follow.sh --enable-motion --max-speed-deg 20
# 环境变量方式：不修改脚本
XCORE_FOLLOW_MAX_SPEED_DEG=10 ./start_gello_follow.sh --enable-motion
```

优先级为命令行参数 > 环境变量 > 脚本默认值。启动时会显示实际采用的限速。
每次更换速度需要先按 Ctrl+C 结束上一次跟随，再重新启动。
有效范围为 `0 < V <= 75°/s`；`75°/s` 是现有软件上限，不代表 CR7 的硬件
最大速度或已经验证的实验速度。可从较低值逐步测试。
加速度仍限制为 `40°/s²`，实际速度还取决于主臂运动、角度差和运动持续时间，
短距离跟随不一定达到设定上限。此参数不改变启动对齐的 `--prepare-speed`。

跟随默认只输出启动信息、错误和停止提示，不循环打印关节／夹爪状态，
也不为终端显示额外查询每帧反馈。需要查看连续状态时显式启用：

```bash
./start_gello_follow.sh --enable-motion --show-state
# 只读预览时查看连续数据
./start_gello_follow.sh --show-state
```

`start_data_record.sh` 同样默认不循环打印；记录反馈、R/S/D/P/H 按键及
故障检查仍正常工作，也支持 `--show-state`。

脚本持有同一把单实例锁，准备、实时跟随和记录不会重叠占用 SDK 或 GELLO。
已手动对齐时，可用 `./start_gello_follow.sh --enable-motion --skip-prepare` 跳过准备
移动，仍保留启动对齐闸门。`--yes` 可跳过交互确认。参数错误、超限目标、
准备期间主臂移动或准备失败都会阻止实时跟随启动。

按 **Ctrl+C** 结束真机实验：先停 GELLO 客户端和夹爪，再关闭实时／准备 SDK 会话，
随后以独占 SDK 会话将六轴回到 `[0°,0°,0°,0°,0°,0°]`。
速度与等待时间沿用 `--prepare-speed`／`--prepare-motion-timeout`；
回零后恢复回零前的电源和模式。再次 Ctrl+C 可停止回零。
故障退出也默认显示原始异常、服务端错误和控制器最近错误／警告，关闭记录与 SDK 后
尝试一次实时故障恢复和回零；完成后下电、切手动，不重启跟随，保留非零退出码。
恢复或回零失败即停止；急停／安全门不自动复位，碰撞检测和软限位保持启用。
只读预览、SIGTERM 或强制清理不回零；`--no-return-zero` 可禁用自动回零。
不要在跟随或回零期间另开 SDK 查询／运动命令。
日志位于 `xcore-sdk-python/logs/follow-*/`：`preparation.json` 保存到位结果，
`server.log` 保存实时跟随日志。

脚本实现位于 SDK 仓库的 [scripts/start_gello_follow.sh](../xcore-sdk-python/scripts/start_gello_follow.sh)，本目录的同名脚本是便捷入口。仅克隆 SDK 仓库时，可直接运行 `./scripts/start_gello_follow.sh`。各操作也保留 `uv run xcore-sdk-python [指令] [参数]` 接口。

控制器入口默认同时跟随六轴和独立外接夹爪，默认服务地址为 `192.168.2.225:5005`。
可用 `--gripper-host` 指定另一台电脑，或用 `--arm-only` 仅启用六轴，见下方。
2026-10-08 已完成 CR7 六轴归零、现场标定及实时跟随实测，用户确认能正常跟随。
新增启动对齐流程有离线覆盖；独立夹爪联动和数采仍需单独完成真机验收。

- [命令与快速启动](../xcore-sdk-python/README.md)
- [工程搭建、模块职责与验证边界](../xcore-sdk-python/docs/DEVELOPMENT.md)
- [历史 CR7／ROS2 仿真调研](../docs/CR7_RESEARCH.md)


## 夹爪服务与 GELLO 仿真

本机现场的远端 `192.168.2.225` 已于 2026-10-08 升级，夹爪服务由
`rokae` 用户级 systemd 在后台管理，正常使用无需再次手动启动。
从当前电脑可检查：

```bash
./start_gripper.sh          # 通过 SSH 启动远端后台服务并检查；已有服务不会重启
./start_gripper.sh --status # 只读检查 TCP 反馈
```

顶层入口默认不打开本机串口。本机的 FTDI `FTB4C7PQ` 属于 GELLO，
将它当作夹爪串口会收不到 Modbus 回复。夹爪串口 `DAAQMP8J` 在远端 `.225`。
如提示 `Gripper target stream timed out`，等待统一跟随和回零退出，再执行
`./start_gripper.sh` 自动发送 stop 清除超时锁定；`--status` 不清除故障。
也可用 `--reset-stream` 显式清除，运行中的跟随锁会阻止恢复／重启。
需要重启服务时使用 `./start_gripper.sh --restart`，服务重启会激活夹爪。

服务随 `rokae` 用户登录启动；管理与部署说明见
[远端夹爪服务](../docs/GRIPPER_SERVER_UPDATE.md)。以下手动启动方法用于其他部署，
不要与当前后台服务同时占用串口或 5005 端口。

在连接夹爪 USB/RS485 的电脑启动夹爪服务：

```bash
# 列出设备；辨认夹爪适配器，与 GELLO 适配器区分
ls -l /dev/serial/by-id/
./start_gripper.sh --local --serial-port /dev/serial/by-id/<实际夹爪适配器名称>
```

上面的串口必须属于夹爪 RS485 适配器，与 GELLO 串口不同；优先使用实际
`/dev/serial/by-id/...` 路径。本机模式要求明确串口，拒绝 GELLO 串口及其别名。
夹爪服务启动会激活夹爪。

服务就绪后，在另一终端运行统一跟随入口；同机服务使用 `127.0.0.1`，
异机服务使用夹爪 USB 所在电脑的 IP：

夹爪终端显示 `0.0.0.0:5005` 表示监听这台电脑的所有网卡，不是客户端的远程
连接地址。服务同机时使用 `127.0.0.1`；服务异机时，在服务电脑运行
`hostname -I` 查询客户端可达的实际 IP，并通过 `--gripper-host` 指定。

```bash
# 本机现场配置：远端夹爪为 192.168.2.225:5005；只读预览
./start_gello_follow.sh

# 远端服务就绪后，对齐并进入六轴与夹爪统一跟随
./start_gello_follow.sh --enable-motion

# 若夹爪 USB 改为接在本机，则覆盖为本机地址
./start_gello_follow.sh --enable-motion --gripper-host 127.0.0.1

# 暂未连接夹爪时，仅测试六轴
./start_gello_follow.sh --enable-motion --arm-only
```

夹爪服务必须先就绪。统一脚本在连接 CR7、打开 GELLO 和准备运动前发送只读
`follow_status`，校验服务能力、激活状态和实际夹爪位置；失败则退出，
不会悄悄改为仅六轴。`--arm-only` 与显式 `--gripper-host` 不能同时使用。
也可设置脚本开头的 `gripper_host` 或环境变量 `XCORE_GRIPPER_HOST`。
SDK 仓库的独立脚本仍按 `--gripper-host`／环境变量启用夹爪。

本机的 CR7 为 `192.168.2.160`，夹爪服务系统的有线 IP 为 `192.168.2.225`；
后者还拥有 WiFi 地址 `10.194.89.200`，当前通过有线地址通信。
若预检查提示只支持 `activate/status/open/close/move`，表示远端仍运行旧服务，
需要升级到支持 `follow_status/set_target/stop` 的版本；仅修改客户端地址不能
启用连续跟随。远端服务管理见 [夹爪服务部署](../docs/GRIPPER_SERVER_UPDATE.md)。

同一客户端每帧读取 GELLO 六轴和 ID 7 扳机，再分别发送到 CR7 六轴服务和夹爪 TCP 服务。
默认六轴 50 Hz、夹爪 5 Hz。夹爪工作线程只发送最新闭合度，不阻塞机械臂目标更新；
服务端允许运动中修改目标。`--gripper-open-deg` / `--gripper-close-deg` 默认
194.8° / 153°，需按实测确认；实际夹爪端点通过 `--gripper-open-pos` /
`--gripper-closed-pos` 设置，速度、力度通过 `--gripper-speed` / `--gripper-force` 设置。

跟随期间仅统一客户端读取 GELLO，不同时启动 `read` 或仿真跟随进程。
Ctrl+C 停止客户端时发送夹爪停止请求，并退出 CR7 跟随；夹爪默认 1.5 s 未收到刷新
会触发服务端停止保护。已完成真实位置保持目标及停止指令通信验证，
全行程开合与实际响应速度仍需跟随实验验收。
启用 `--show-state` 后，输出中的 `gripper_target` 是 GELLO 扳机映射的 0～1 闭合度，
`gripper_feedback.position_raw` 是实际从臂夹爪反馈；两者同时显示以便核对跟随。
完整参数与测试边界见 [SDK README](../xcore-sdk-python/README.md)。

## 从臂六轴与夹爪数据记录和转换

确保远端夹爪服务运行，再启动记录入口。它包含统一跟随流程，不同时启动普通
`start_gello_follow.sh` 或其他 GELLO 读取进程；启动时按已有标定先对齐到
主臂当前目标，再跟随和记录。记录入口也支持 `--prepare-*`、`--skip-prepare`
和首次 `--calibrate-zero` 参数。

```bash
./start_data_record.sh --task "pick up the object"
# 自定义夹爪地址、数据集帧率，并在对齐后立即记录第一段
./start_data_record.sh --gripper-host 192.168.2.225 --task "pick object" \
  --dataset-fps 30 --start-recording
```

R 开始 episode，S 保存，D 丢弃，P 查看状态，H 查看帮助。
Ctrl+C 先停止跟随并关闭 SDK 服务，再将六轴回零，回零会话关闭后转换已经保存的 episode。
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
说明见 [数据记录与转换](../docs/DATA_RECORDING.md)。
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
