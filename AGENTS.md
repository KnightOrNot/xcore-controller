# xcore-controller 协作说明

本文用于让后续 AI 接手工程。先阅读本文、`README.md` 和将要修改的子项目文档；
以代码、现场配置和实际测试结果为准，不能将历史日志或计划当作已验收功能。
最后更新：2026-10-21。默认参数已统一到各项目的 `config/default.toml`，文档结构对齐
agilex；双相机第一版已部署并通过硬件采集测试，验收边界与本次交接见文末。

## 用户目标和工程边界

- 将 GELLO 主臂六轴和扳机映射到 ROKAE xMate CR7 从臂及 Robotiq 2F-85 夹爪，
  通过一个顶层 `.sh` 完成日常启动。无需 ROS2、MoveIt 或仿真跟随启动链。
- 工程结构、独立子项目、CLI 和脚本组织参考相邻 `agilex*` 项目；
  CR7 驱动接口、实时运动方法参考相邻 `gello for CR7` 项目。不要将后者整个工程照搬。
- 实现从臂反馈数据记录、片段保存及 LeRobot 数据转换；相机项目负责采集、信息和预览，
  新数据链的原始数据汇集、LeRobot 转换与 LeLab 数据管理在远端完成，本地按需经有线网络拉取。
  数据适配／转换属于独立项目，不修改其他项目共用的 `lerobot-converter`，详见文末规划。
- 新增远端两台 RealSense D435i 的启停、信息读取、RGB＋深度实时预览及截图。
  在本地发命令，通过 SSH 管理远端服务并在本地浏览器查看画面。
- **当前任务不要移动机械臂，不要启动跟随或执行退出返回。** 相机开发与真机控制解耦。

## 仓库布局与 Git 规则

```text
xcore/
├── xcore-controller/              # 集成仓库：脚本、文档、工具、测试、submodule 指针
│   ├── config/default.toml        # controller 默认参数（唯一来源）
│   ├── docs/                      # 架构、安装、相机、CLI/配置/排障
│   ├── scripts/                  # 所有 controller shell 命令：setup/start/stop
│   ├── tools/                     # config_defaults.py、convert_cr7.py
│   ├── tests/                     # 父仓库离线测试
│   ├── xcore-sdk-python/          # CR7 SDK 封装、RT 跟随、记录；独立 Git 子模块
│   ├── xcore-gello-software/      # GELLO 只读采集和标定支持；独立 Git 子模块
│   ├── xcore-gripper-2F85/        # 夹爪驱动、协议、服务源码；独立 Git 子模块
│   ├── lerobot-converter/         # 独立转换环境；独立 Git 子模块
│   └── camera-realsense-d435i/    # 独立相机仓库的 submodule
└── camera-realsense-d435i/        # 独立相机开发 checkout
```

五个 submodule 都遵循同一结构：`config/default.toml`、`docs/`、
`docs/reference/{cli,config,errors}.md`、`CONTRIBUTING.md`、`CHANGELOG.md`。
源码包的 `default.toml` 是指向仓库配置的符号链接。

父目录还可能有 SDK、GELLO 等其他独立 checkout；修改前核实 `pwd`、Git 根目录和远端，
不要误改同名副本。当前集成运行使用 `xcore-controller/` 内的子模块。
相机仓库远端为 `git@github.com:KnightOrNot/camera-realsense-d435i.git`。
用户明确要求相机源码独立存放在 `xcore/` 下，控制仓库只通过 submodule 引用源码，
并提供顶层入口；不要把相机源码直接纳入控制仓库。

先分别检查父仓库和子模块 `git status --short`。工作区可能有尚未提交的用户／协作改动；
保留它们，不要 `reset --hard`、清理现场配置或用批量提交混入无关变更。
子模块修改先在子仓库提交，再更新父仓库指针；发布时先推送子仓库，再推送父仓库。
用户仅要求 commit 时不自动 push。正常部署使用固定版本，
不要随意 `submodule update --remote`。强推只有当次明确授权才执行。
不要把密码、SSH 私钥、相机画面、现场标定、数据集或 `.venv` 提交到 Git。

## 默认配置与文档约定

- controller 与五个 submodule 各自有 `config/default.toml`，默认参数只写在这里；
  不要再在代码或 shell 中复制第二份默认值。
- 优先级：显式命令行参数 > 已存在的 `XCORE_*` / `GRIPPER_*` 环境变量 >
  TOML > 内置默认值。controller 用 `XCORE_CONFIG` 选择另一份配置。
- controller 脚本通过 `tools/config_defaults.py` 读取，不解析 TOML 文本。
- 各包的 `src/<package>/default.toml`（GELLO 为
  `xcore_gello_software/default.toml`）指向仓库配置，避免安装后出现第二份。
- 现场标定、退出姿态、相机 JSON、数据集和日志仍使用 Git 忽略文件，
  不写入 `default.toml`。
- 文档骨架与相邻 agilex 项目一致：根目录 `README.md`、`CHANGELOG.md`、
  `CONTRIBUTING.md`、`THIRD_PARTY_NOTICES.md`（controller 还有 `AGENTS.md`），
  以及 `docs/index.md`、`docs/installation.md`、
  `docs/reference/{cli,config,errors}.md`；相机和 controller 另有
  `docs/cameras.md` / `docs/stream.md`，controller 还有
  `docs/reference/submodule-config.md`。

## 当前现场连接

| 设备 | 位置／地址 | 注意事项 |
| --- | --- | --- |
| 控制电脑 RON | 有线通常 `192.168.2.100/24` | WiFi 提供外网；有线无默认网关，实际地址先检查 |
| CR7 控制器 | `192.168.2.160` | 与下方 Linux 主机不同，不要混淆 |
| Linux 服务电脑 rokae-zju | `rokae@192.168.2.225` | SSH 密钥登录；远端 Ubuntu 22.04 x86_64 |
| GELLO | 接本地 USB | `/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0`；57600，ID1～6＋扳机 ID7 |
| Robotiq 夹爪 | 接远端 USB/RS485 | 远端 FTDI RS485 适配器，不是 GELLO 串口；TCP 5005 |
| D435i cam1 | 接远端 USB | 序列号 `349522071221`；当前 USB 2.1 |
| D435i cam2 | 接远端 USB | 序列号 `349522072318`；当前 USB 2.1 |

地址和串口是当前现场值，不保证换机器后成立。SSH 凭据通过已有密钥／用户提供方式获取，
不在本文保存。远端 `~/project/` 是用户要求的项目根目录。

2026-10-21 巡检：远端**没有检测到夹爪 RS485 适配器**
（`/dev/serial/by-id/` 不存在，`lsusb` 无 FTDI 设备），
`xcore-gripper-follow.service` 曾因串口缺失处于 `auto-restart`。硬件恢复前应保持该
unit 停止，不要通过反复重启或改用其他串口“修复”，也不要为相机开发顺带处理夹爪。

## 已有跟随与夹爪功能

- 顶层 `scripts/start_gello_follow.sh`：先检查夹爪、SDK、GELLO 和标定；
  `--show-state` 用于只读预览，`--enable-motion` 经现场确认后才对齐并跟随。
  默认裸命令不授权运动。六轴和夹爪共享一次主臂读取，服务分开。
- CR7 SDK 位于 `xcore-sdk-python/`，CPython **3.11**、Linux x86_64；
  二进制为 `Release/linux/xCoreSDK_python.cpython-311-x86_64-linux-gnu.so`，SDK 0.7.1。
  CLI 的实际入口以 `pyproject.toml`、`--help` 为准，可用 `uv run --project xcore-sdk-python xcore …`。
  不要用其他 Python ABI 的扩展替代。
- 六轴实时跟随的软件速度上限为 75°/s、加速度 40°/s²；启动对齐 SDK 参数目前 4000 mm/s。
  SDK 速度参数不等于轴速度，更不能视为已测得硬件最大速度。
- `follow_limits.py` 统一准备与 RT 使用的限位交集；起始真机姿态和目标都必须通过检查。
  之前的 J1 +183.5°、J6 +176.7° 报错分别涉及限位，不要通过删除检查、自动截断或
  无条件 ±2π 包装来“修复”。实际关节空间和现场标定必须明确。
- `config/cr7_calib.json` 为现场标定，通常被 Git 忽略；新 clone 不能凭空运行真机跟随。
  启动对齐需要保持主臂不动；旧会话完全退出前不能启动第二个会话。
- 退出行为已从六轴回零改为返回用户指定的实测姿态；现场文件
  `xcore-sdk-python/config/exit_pose.json`，可用 `XCORE_EXIT_POSE`／`--return-pose-file` 覆盖。
  当前保存角度（°）约为 `[179.1866, 26.4200, -73.5113, 5.7521, -78.9521, -0.3129]`。
  文件来自 2026-10-21 实际反馈；它不是每次退出时重新采集的起点。
  `return-pose` 是规范命令；兼容 `return-zero` 的历史入口也要核实当前代码语义，
  只有显式 `--zero` 才要求六轴 0°。新 clone 应先提供自己的有效返回姿态，不能静默退回零位。
  `--no-return` 可禁止自动返回；退出返回本身是真实运动。
- 夹爪源码 `xcore-gripper-2F85` **有用**：是协议和服务实现、部署来源，
  不是应删除的重复目录。远端 `xcore-gripper-follow` 是部署项目，提供夹爪反馈、
  连续目标跟随、停止和流状态；不控制 CR7 六轴，不采集 GELLO，不提供相机功能。
- 远端夹爪实际目录：`~/project/xcore-gripper-follow/current`，相对链接指向 `releases/`。
  用户 unit `xcore-gripper-follow.service` 的 WorkingDirectory 和 PYTHONPATH 已同步迁移，
  用户随后要求按需启动，当前 unit 已 disabled（不开机／登录自启），由本地
  `scripts/start_gripper.sh` 执行 SSH `systemctl --user start`。`Linger=yes` 保留，
  用于 SSH 断开后继续运行，不会自动启动已 disabled 的设备服务。迁移备份在
  `~/.local/state/xcore-gripper-migrations/20261021T160259+0800/`。
  已验证服务停启和反馈，没有为了迁移测试夹爪开合或重启远端整机。
- `scripts/start_gripper.sh` 管理远端服务，`--status` 只读；重启／首次启动可能激活夹爪。
  结束六轴跟随与退出返回后才能停／改夹爪服务。禁止为相机开发顺带重启夹爪。

## 数据记录

`scripts/start_data_record.sh --task "…"` 进入记录流程；R 开始、S 保存、D 丢弃、P 状态、H 帮助。
现有七维流程的原始数据 `data/raw/`，转换结果 `data/lerobot/`；未保存片段保留 `.partial`。
记录的是从臂反馈，不能用目标角冒充实际角。故障恢复和退出返回不写进 episode。
参考 `docs/DATA_RECORDING.md` 与 `tools/convert_cr7.py`。
转换使用独立 Python 3.12 环境，不能把转换依赖塞入控制 SDK 环境。
上述路径和命令描述已实现的旧流程；新 EE10＋双 RGBD 链路以文末远端数据流程为目标，
尚未部署，不能将现有本地转换入口当作新流程已经可用。

## 远端双 D435i：当前实现

用户已确认需要**两台相机**，各自 RGB＋深度页面；第一版包括远端服务启停、设备信息、
本地实时预览和截图，不要求 ROS2；最新数据需求已要求两路 RGBD 接入数据记录，
见文末“新数据需求”，该采集链路尚未实现。IMU 采集未纳入当前需求。

设计：每台相机一个独立实例，显式绑定序列号和不同端口；远端一个实例只有一个 pipeline，
多浏览器共享最新帧缓存，不能每个查看者重复打开设备。HTTP 仅绑定远端 loopback，
本地通过 SSH 转发访问，禁止默认在局域网公开无认证的相机控制端口。
cam1/cam2 分别使用 8086/8087；本地页面为 `http://127.0.0.1:8086` 和
`http://127.0.0.1:8087`。实例名、端口和序列号一一对应。

相机远端部署目录 `~/project/camera-realsense-d435i/`，使用独立 `.venv`。
现已安装 pyrealsense2 2.59.1、NumPy 2.5.4、Pillow 12.3.0（远端 Python 3.13），
已用普通 rokae 用户枚举到两台设备及 RGB8/Z16 640×480 的 6/15/30fps profiles。
**枚举支持不代表两台能同时达到任意帧率**。目前已验证两台同时 640×480、15fps；
10 秒内每台缓存均推进 150 帧，四路 RGB／深度 MJPEG 均收到有效 JPEG。
本地客户端使用标准库，不要求本机连接相机或安装 RealSense SDK。
2026-10-21 巡检：cam1 固件 5.17.3.10，cam2 固件 5.15.1.55（未升级）；
两台挂在同一个 USB 2.0 Hub（480 Mbps）下，带宽共享。

数据语义：预览深度伪彩 JPEG 仅用于查看。本地 `snapshot` 解压后的目录包含
`color.jpg`（当前 JPEG 质量，**不是**无损 RGB）、`depth.png`（原始 Z16
无损 16 位 PNG）和 `metadata.json`（depth scale、各流内参、外参、独立帧号、
时间戳及 timestamp domain）。不要把 `color.jpg` 当作无损原图。
默认保留原生深度视角；没有显式对齐时，不能直接将 RGB 同像素与深度一一对应。
设备时间与主机 monotonic 时间不得混用；当前远程预览不是双机硬同步或与机械臂同步采集。
导入模块、`--help`、客户端状态查询不得隐式打开本机相机。

相机参考工程为 `git@github.com:KnightOrNot/camera-realsense.git`，
参考 checkout 可在 `/tmp/xcore-camera-realsense-reference`；不要修改原工程来替代新独立仓库。
实现优先使用新仓库 `src/camera_realsense_d435i/` 下的 camera、manager、server、client 和 CLI。

日常命令在控制仓库运行：

```bash
./scripts/start_camera.sh --no-open     # 两台：SSH 连接、采集，打印页面；去掉 --no-open 可尝试打开浏览器
./scripts/start_camera.sh status
./scripts/start_camera.sh snapshot     # 本地 captures/cam1/、captures/cam2/，被 Git 忽略
./scripts/start_camera.sh stop         # 释放两台设备，API 留在 idle
./scripts/start_camera.sh disconnect   # 仅关闭隧道，应该先 stop
```

单台加 `--camera cam1`／`--camera cam2`；远端用 `XCORE_CAMERA_SSH_TARGET=user@host` 覆盖。
独立仓库 CLI 为 `uv run --locked camera-realsense-d435i …`，本地客户端不装 SDK。
远端用户 unit 为 `camera-realsense-d435i@cam1.service`／`@cam2.service`，均已 disabled；
**不开机／登录自启**。本地 `preview`／`connect` 经 SSH 按需启动 API，随后才按命令采集。
关闭网页不会停止采集。安装脚本默认 disable，不要为当前现场传 `--enable` 恢复自启。
持久配置在 `~/.config/camera-realsense-d435i/cam1.json` 和 `cam2.json`，
修改后先停对应采集，再重启对应 unit。不要为了相机变更重启整机或夹爪。
安装脚本 `deploy/install_service.py` 会保留已有 JSON，不会用仓库默认值覆盖现场配置。

## 验证和交接规则

- 离线安装入口 `./scripts/setup.sh --skip-submodules`；`./scripts/setup.sh --check-only` 不连接硬件。
  setup 会检查 controller 与五个 submodule 的 `config/default.toml` 是否存在。
- 根据修改范围运行父仓库／相应子模块 pytest 和 Ruff，不要为检查文档而启动硬件。
  SDK 离线检查为 `uv run --project xcore-sdk-python xcore doctor`。
  父仓库测试使用 `./lerobot-converter/.venv/bin/python -m pytest tests -q`，
  其中转换测试需要转换项目依赖，不能直接拿缺少该包的 SDK 环境运行全部父仓库测试。
  各子项目在其目录内运行：SDK `uv run --project . pytest -q`；夹爪和相机
  `uv run --project . --with pytest --with ruff pytest -q`；转换器
  `./.venv/bin/python -m pytest -q`。
- 修改配置加载后至少运行 `python3 tools/config_defaults.py --json`、对应项目的配置测试
  和 `--help`；这些检查不得打开串口、连接 CR7 或启动相机。
- 新增参数先写入对应项目的 `config/default.toml`；不要在脚本和代码里保留第二份默认值。
  显式 CLI 参数优先，已存在的环境变量优先于文件。
- 不在现有跟随会话运行时发起另一个 SDK 连接；不要自动发起运动测试。
- 相机测试至少覆盖启动／停止／重启、断流与异常传播、原始深度格式、双机同时预览。
  实测帧率、USB 模式、截图和测试结果写入相机 README；未测试项明确标记。
- 不要记录或提交登录密码、SSH 私钥和本地敏感画面；保留现场配置与业务数据。
- 默认只提交当次任务范围；用户明确要求提交全部项目改动时，先审阅父仓库及各子模块，
  排除现场配置／数据，再按子仓库到父仓库的顺序提交。
- 功能或部署状态变化后更新本文，写清“代码已实现”“离线测试通过”“硬件已实测”的区别。

**相机交接状态（历史记录，2026-10-21）**：相机项目已推送到新仓库 main，提交
`49b6293`，父仓库已引用同版本 submodule。
`scripts/start_camera.sh`、五环境 `scripts/setup.sh` 和 README 已接入。
相机离线 pytest 10 项通过，Ruff 检查及格式检查通过；五个子项目的环境入口检查通过。
父仓库现有离线测试在转换环境运行，25 项通过。
远端已部署两个独立空闲 API，监听地址经核实均为 127.0.0.1。
真实双机采集、四路 MJPEG、截图 RGB／uint16 深度、单机停启、非法 profile 失败及恢复、
另一实例会话不受影响均已验证。最终顶层脚本也完成了双机启动→状态→停止→断开链路。
测试结束后两台采集已停止，SSH 相机隧道已断开；用户重新执行启动命令即可预览。
后续用户又启动了相机；取消自启时检测到两台相机服务 active，已只执行 disable，
没有停止／重启当时正在运行的相机会话。夹爪和两台相机均已验证为 disabled，
并保留 SSH 和用户管理器以供本地按需启动；没有通过重启整机验证。
相机部署脚本已改为默认 disable，并已同步远端；实测重复安装后仍 disabled，
两个相机服务 PID 保持不变。当前服务的按需 SSH start 路径未改变，不会恢复开机自启。

尚需人工验收：本工具环境没有可用自动化浏览器，网页 HTTP 和实际图像流已验证，
页面排版和浏览器按钮点击尚未自动化验收。cam2 当时 RGB 画面看似贴近遮挡物，
深度非零约 1%，需现场检查朝向、遮挡与距离；cam1 当时约 77%。
未为此调整现场相机位置、升级固件或改变 USB 连接。
双机硬同步、IMU、连续录像和机械臂数据记录接入仍未实现；最新数据需求已确认
两路 RGBD 记录及时间对齐，见文末。不能将现有预览能力当作已完成数据记录。

2026-10-21 用户要求将当前全部项目改动 commit。SDK 的共享限位、拒绝启动错误传播、
保存姿态返回及配套测试／文档已提交为 `1d8474d`。
控制仓库将相机子模块、统一 scripts 入口、停止服务脚本、文档和测试一并纳入本次本地提交，
固定上述 SDK 版本。本次未执行 push；后续发布必须先推送 SDK，再推送控制仓库。
现场标定、退出姿态 JSON、日志、数据、虚拟环境仍不纳入 Git。

## Controller 脚本入口

用户要求 controller 自身所有 `.sh` 放在 `scripts/`，根目录不保留旧入口。
五个原入口已迁移，脚本都根据自身位置解析仓库根目录，支持从其他工作目录调用。
子模块拥有的脚本保留在各自仓库，不能跨 Git 边界搬动。

脚本默认值来自 `config/default.toml`，通过 `tools/config_defaults.py --shell` 读取；
`XCORE_CONFIG=/path.toml` 可选择另一份配置。已存在的 `XCORE_*` 环境变量优先于文件，
命令行参数优先于两者。脚本仅在配置和工具均不存在的历史测试夹具中跳过加载。
若只缺失其中一项，必须报错退出，不能静默使用内置运动参数。

- `scripts/setup.sh`、`scripts/start_gello_follow.sh`、`scripts/start_data_record.sh`。
- `scripts/start_gripper.sh` 按需启动；`scripts/stop_gripper.sh` 完全停止远端服务。
  后者持有与跟随相同的 `xcore-sdk-python/.follow.lock`；占用时拒绝 SSH stop。
- `scripts/start_camera.sh` 按需启动；其 `stop` 子命令仅停止采集，API 保留。
  `scripts/stop_camera.sh` 完全停止远端 API 并清理对应隧道，默认两台，支持 `--camera cam1|cam2`。
  远端 stop 失败时保留隧道，不假装成功。
- 停止入口的验证使用隔离的 SSH／CLI stub，不应为了测试脚本而终止用户正在使用的服务。

脚本迁移时的验证（历史记录）：父仓库 34 项离线测试通过，新增测试覆盖夹爪占锁拒绝停止、
相机单台／双台选择、SSH 失败时保留隧道及非法参数在 SSH 前拒绝；
七个脚本的 shell 语法和帮助通过，五环境检查通过。未执行真实远端 stop。
SDK 完整离线测试 200 项通过，Ruff 检查通过；controller 离线测试 34 项通过。
这些结果不替代现场运动验收，本次提交过程中未连接或操作机械臂。

## 配置与文档改造交接（2026-10-21）

已完成并通过审查：

- controller 与五个 submodule 均新增 `config/default.toml`、配置加载模块和覆盖入口：
  SDK/夹爪/转换器用 `--config`，相机用 `--defaults`（`serve --config` 仍是现场 JSON），
  GELLO 用 `XCORE_GELLO_CONFIG`。
- controller 新增 `tools/config_defaults.py`；七个 shell 入口读取 TOML，
  `setup.sh --check-only` 校验六份配置文件存在。
- 文档骨架对齐 agilex：controller 新增 `docs/index.md`、`docs/installation.md`、
  `docs/cameras.md`、`docs/reference/{cli,config,errors,submodule-config}.md`、
  `CHANGELOG.md`、`CONTRIBUTING.md`、`THIRD_PARTY_NOTICES.md`；五个 submodule
  补齐 `docs/` 和根文档，README 增加配置与文档入口。
- 现场文件仍不进入 Git：`cr7_calib.json`、`exit_pose.json`、远端 `camN.json`、
  数据集、日志、截图。

验证结果（全部离线，未连接机械臂、未启动相机采集、未操作夹爪）：

| 范围 | 结果 |
| --- | --- |
| SDK | 214 passed；Ruff 和格式检查通过 |
| controller | 53 passed |
| 夹爪 | 45 passed + 6 subtests |
| 转换器 | 7 passed |
| 相机 | 18 passed |
| GELLO | 16 passed（`tests/`，不包含未使用的 ROS2 工程） |
| 其他 | 五个 wheel 均包含默认配置；SDK sdist 包含配置；Python 3.8 GELLO、Python 3.10 GELLO/夹爪配置导入通过；配置工具、脚本帮助、`xcore doctor` 和变更文档链接检查通过 |

审查修复：

- 默认截图采用每次独立时间戳目录，重复调用不因目录已存在失败。
- controller 配置的夹爪端口传入 SDK 跟随入口，显式 CLI 仍优先。
- 直接 SDK 准备／返回命令保持历史默认 1000 mm/s；controller 仍按其配置显式传入速度（当前 4000 mm/s）。
- GELLO Python 3.8–3.10、夹爪 Python 3.9/3.10 使用条件依赖 tomli，保持原声明兼容性。
- SDK 的 --config、相机的 --defaults 支持子命令前后；拒绝非法配置类型、端口、非有限数值，检查 shell 环境覆盖值。
- 配置或工具单独缺失时在设备操作前报错；第三方说明不自行声明未知的厂商再分发禁令。

本轮本地离线测试合计 353 项及 6 个 subtests。用户已授权本轮 commit 与 push；
顺序是先五个 submodule，再更新父仓库指针并提交／推送 controller。
未执行远端部署或真机操作，相机和夹爪的现场硬件状态未因本次审查改变。

尚需人工验收：真实跟随、退出返回、夹爪实际开合、相机页面排版与按钮交互。
夹爪 RS485 适配器当前不在远端，硬件恢复前保持 `xcore-gripper-follow.service` 停止。

## 新数据需求：末端 10 维＋双 RGBD＋两路力数据（已确认，待实现）

2026-10-21 用户确认以下方案，并补充：**力数据有两路，每路六维，共 12 维**。
图像要求已明确为**两台相机各一组 RGBD（RGB＋原始深度）**，合计两路彩色与两路深度；
深度记录属于本次需求，不能只记录 RGB 或用深度伪彩预览代替。
详细依据见 [数据方案](docs/DATASET_EE10_DESIGN.md)。当前只完成样例检查和方案记录，
未实现新采集、同步或导出链路；本次文档整理不授权运动测试。

### 参考样例与目标格式的区别

用户新增 `xcore/episode_000000.parquet` 作为参考。已检查到 99 帧、约 10 Hz；
用户随后已确认样例为双臂数据，`state[20]` 对应两臂各 10 维；
左右顺序仍需字段说明确认，`actions[21]` 最后一维语义未知，
图像实际为三路 224×224 RGB（`image`、`left_wrist_image`、`right_wrist_image`）。
每组姿态的六维数值满足两个单位正交向量，但样例没有逐维说明，不能仅凭数值
确认旋转矩阵的行／列、坐标系、单位或 TCP。夹爪样本均为 0，不能推断开合方向。
`adv_ind="positive"` 不能直接当作任务指令；未知的第 21 维不能当作夹爪、力或终止标志。
当前只有单台 CR7，不为兼容样例伪造第二臂、第三路图像或额外 action。

### 已确认的数据契约

```text
pose10 = [x, y, z, R00, R10, R20, R01, R11, R21, g]
                  R 的第一列       R 的第二列
wrench12 = [Fx1, Fy1, Fz1, Tx1, Ty1, Tz1, Fx2, Fy2, Fz2, Tx2, Ty2, Tz2]
```

- `pose10` 是 10 维特征表示，不是机械臂具有 10 个独立物理自由度。
  位置用米，R 表示基座坐标系中的工具 TCP 姿态；实际和目标必须使用同一模型与 TCP。
  显式使用 `concatenate([R[:, 0], R[:, 1]])`，不能直接对 `R[:, :2]` 默认 flatten。
  `g` 沿用现有闭合度定义：0 全开、1 全闭，在元数据中明确；训练端需要时由导出层转换。
- 下表是单 CR7 的目标数据内容，具体字段名由导出适配确定，不能仅改扩展名冒充其他格式。

| 内容 | 数据契约 |
| --- | --- |
| 实际状态 `state` | float32[10]：实际从臂 TCP 位姿＋实际夹爪闭合度 |
| 动作目标 `action` | float32[10]：观测 t 之后请求执行的绝对目标 TCP 位姿＋目标夹爪闭合度 |
| 两路 RGBD | 两台 D435i 各自记录 RGB＋原始深度；每台的 color/depth 分别保留帧号和时间戳 |
| 力数据 `wrench` | float32[12]：两路各六维，依次为 Fx/Fy/Fz（N）、Tx/Ty/Tz（N·m） |
| 力有效性 `wrench_valid` | bool[2]，每路独立；无传感器时为 false，不能将占位零值当作实测 |
| 字符串 `instruction` | 自然语言任务描述；episode 内固定内容可存一次，再通过索引关联 |
| 时间与有效性 | state、action、两台相机的各路 color/depth、两路力各自的时间戳、时钟域、匹配误差及缺失标记 |

每台相机的深度保存为无损 uint16/Z16 数据（如 16 位 PNG），并保存 depth scale、
color/depth 内参及二者外参，明确深度数值到米的换算。不能保存为 8 位图、普通有损视频
或伪彩 JPEG 来替代原始深度。保留原生深度；如另生成对齐 RGB 的深度，需标注对齐方式、
目标坐标系与无效像素，不能默认认为原生 RGB 与深度同像素对应。

两路力分别保存传感器标识、参考坐标系和单位，不能假设两路来自左右臂；具体安装位置
和设备尚未确认。未接入时只预留字段与无效标记，不把控制器估计量冒充力传感器实测。
动作目标不能直接用下一帧实际状态替代。采集时区分请求目标、限位后接受的目标和
RT 插值输出，训练特征明确选择哪一种；未来实际状态如需保存，另设字段和时间间隔。

### 实现边界与实施顺序

1. **先完善采集层和运动学**：现有 raw 主要是六轴关节＋夹爪的七维数据；
   `gello_follower.get_observations()` 的 `ee_pos_quat` 仍是全零占位。
   在现有唯一 SDK 会话内读取真实末端反馈，或对同帧关节执行已验证的 FK；
   目标关节使用同一实际 CR7 模型和 TCP 计算目标末端位姿，不能使用 GELLO 本体模型代替。
   保留原始关节、目标来源、标定、模型版本和时间戳。记录器不能另开并发 SDK 会话，
   网络和写盘不能放进 RT 回调，应使用独立队列／工作线程。
2. **补齐图像记录与时间对齐**：在远端已有单 pipeline 中增加后台记录分支，不能重复打开相机。
   HTTP/MJPEG 是有损、允许跳帧的预览，不是训练数据记录；如需无损 RGB，在 JPEG 编码前保存。
   两台相机均需记录 color 和原始 depth；每台 RGBD 配对及两台相机之间的匹配误差、
   缺帧有效性都需保留。深度使用无损数据通道，不复用彩色视频的有损编码。
   本地机械臂与远端相机需建立时钟映射，保留偏移／漂移估计、逐流时间戳和匹配有效性。
   不直接比较不同主机的 monotonic 时间，也不把网络到达时间当作曝光时间。
   两路力同样分别记录时间戳和有效性，不能重复低频测量伪装成高频新数据。
3. **独立实现数据处理与导出**：用户明确要求**不得修改共享 `lerobot-converter`**，
   因为其他项目仍依赖它。最新要求为远端使用 LeRobot、LeLab 与自编 adapter 完成数据流程，
   采用下节 `xcore-adapters`＋`xcore-dataset` 的职责划分；不再将单个本地导出脚本作为主方案。
   controller 按需通过 submodule 引用，只提供 `scripts/` 中的薄入口。
   不修改、monkey-patch 或依赖旧转换器的私有七维实现，也不修改上游 LeRobot／LeLab 源码。
4. **版本与验证**：新 raw/schema 另设版本，保留原七维采集／转换链路。
   标准 LeRobot 导出使用 `observation.state`、`action` 及对应 features、任务和图像元数据；
   训练端需要样例列名时另做显式映射。校验旋转正交性、夹爪范围、两路力掩码、
   RGBD 配对、深度 dtype／scale／标定、跨流帧龄／掉帧和 episode 边界；
   先离线验证，再单独安排硬件采集验收。

已有七维数据在具备匹配的模型／TCP 时可以离线重算末端表示；未采集的图像和力数据
无法通过转换器补回。新采集链路、独立数据项目和训练格式验收均仍待实现。

## 远端采集、LeRobot／LeLab 与本地按需拉取（规划，待实现）

### 用户要求与参考流程

用户已要求：**采集后在远端转换为 LeRobot 格式，使用 LeRobot、LeLab 和自编 adapter，
本地需要时再经网线传回数据**。这不是要求迁移现有 GELLO／CR7 实时控制位置。
目前 GELLO 和 SDK 控制仍在本地；远端接收记录副本并拥有相机采集、数据存储和转换。
后续 AI 应以本节为最新数据架构，不把早期“本地独立导出”建议当作最终流程。

已只读参考 `../agilex/agilex-controller/` 的这些实现（相对 `xcore/` 根目录）：

- `README.md`、`docs/index.md`、`docs/cameras.md`：存在“CLI raw 后转换”和
  “浏览器直接写 LeRobot”两条并行链，原始数据、输出和环境分离。
- `src/agilex_data_collection/session.py`：通过 `LeRobotDataset.create/add_frame/`
  `save_episode/finalize` 写数据，保存原始 RGB/Z16、标定和采样审计。
- `agilex-adapters/src/agilex_adapters/{devices,transport}.py`：LeRobot
  Robot／Teleoperator 协议与硬件 worker 分离，adapter 不拥有底层设备。
- `src/agilex_data_collection/runtime.py`：集成 LeLab 数据集浏览和管理，数据根目录一致。

参考工程的浏览器链是直接写入而非再次调用旧 converter；本项目选择先完整保存 raw，
再在远端后台转换，以便重试、核查同步和避免编码影响实时跟随。
**LeRobot 负责数据集格式和写入／读取；LeLab 负责浏览、回放和管理，不是转换引擎；
自编 adapter 负责 CR7 数据语义、同步和字段映射。** 不照搬 PiPER 的七维 schema、
CAN 初始化、回零逻辑或同机时钟假设。

### 拟定组件、目录和运行环境

| 组件 | 位置／职责 |
| --- | --- |
| controller | 本地编排、现有跟随控制、采样副本发送、SSH 管理及按需拉取；所有 shell 入口仍在 `scripts/` |
| 现有 SDK／GELLO | 本地唯一设备 owner；提供同一采样记录中的实际反馈、请求／接受目标及时间信息，不新增控制循环 |
| camera-realsense-d435i | 远端两台相机的唯一 pipeline owner；增加 RGBD 原始帧记录分支，与预览共享采集 |
| xcore-adapters（拟新增） | 独立适配包：CR7／GELLO LeRobot 协议、采样数据契约、FK／EE10、特征和深度／力字段映射；不直接另开 SDK／串口 |
| xcore-dataset（拟新增） | 远端 session／episode 协调、raw 接收与封存、时间对齐、LeRobot 转换任务、质量报告及 LeLab 集成；依赖 xcore-adapters |
| LeRobot／LeLab | 远端独立数据环境中的锁定依赖；数据处理应用调用其 API，不改上游代码 |

拟新增项目源码在本地 `xcore/xcore-adapters/`、`xcore/xcore-dataset/` 独立维护，
controller 仅通过 submodule 引用并集成入口；仓库尚未创建，不得写成已存在或已部署。
远端部署在 `~/project/xcore-adapters/`、`~/project/xcore-dataset/`，
业务数据统一放 `~/project/xcore-data/`，与代码／虚拟环境分开并排除 Git。

```text
~/project/xcore-data/                 # 拟定远端数据根目录，可配置
├── raw/<session_id>/                 # manifest、episode、状态/目标、双 RGBD、两路力、时钟审计
├── staging/<job_id>/                 # 未完成的转换输出，不供 LeLab 或本地正式使用
├── lerobot/<dataset_id>/<revision>/  # 校验完成、不可变的数据集版本
├── reports/<job_id>/                 # 质量报告、错误、任务与源 raw 标识
└── logs/                            # 接收、采集、转换及服务日志
```

LeRobot／LeLab／adapter 采用独立 Python 3.12 环境作为参考起点，依赖版本和 CPU
Torch／FFmpeg／视频后端以远端兼容性测试及 `uv.lock` 固定，不盲目追最新版。
本地 SDK 保持 CPython 3.11；远端现有相机环境保持独立，不为数据工具改其 Python ABI。
参考工程当前锁定 LeRobot 0.6.0 和 LeLab 提交
`9b5afaee33baa1d773e499937564f3831d25de22`，仅作为已检查的参考组合，
部署前需在远端验证双 RGBD、12 维力、有效掩码和字符串的真实写入／读回。

### 端到端流程与数据完整性

1. **按需准备**：本地通过 SSH 启动远端数据服务、必要的相机服务及隧道，
   查询磁盘空间、依赖、两台相机和时钟质量。沿用不开机自启的约定；启动数据浏览／转换
   不隐式上电机械臂、激活夹爪或启动跟随。浏览和离线转换不需要相机在线。
   远端 HTTP 绑定 loopback，本地经 SSH 隧道访问；同机 worker 可用私有 Unix IPC，
   跨机使用明确 schema 的受限传输通道，不把 pickle IPC 直接暴露到网络。
2. **建立 session**：分配唯一 session／episode ID，记录任务字符串、设备 serial、
   模型／TCP／标定、完整字段定义、各流 profile、数据频率、时间映射和代码版本。
   新 raw 标记独立格式／版本，不能冒充旧七维 converter 输入。
   数据频率独立配置，先按实测最慢必需流确定；样例约 10 Hz 只是起点，不构成已确认指标，
   不能照搬 agilex 的 30 FPS，当前双 D435i 共用 USB 2.0 带宽。
3. **记录到远端**：本地从现有唯一反馈／跟随通道复制一份完整记录，经有界队列异步发送，
   带 session、序号、源时间、实际关节／夹爪、目标及目标来源；远端返回持久化确认。
   同步记录远端夹爪反馈和两路力（未接入力时掩码为 false），相机原始 RGB/Z16 直接在
   远端落盘，不先把大图传回本地再上传。可保留本地临时 spool 以便确认前重传，
   按 session＋序号去重；本地副本不是另一套正式数据来源。
   网络和磁盘不阻塞 RT；录制队列满、断流、重传缺口或写盘错误须显式标记当前集失败，
   不能静默丢失后还宣称完整。记录失败与跟随停止策略分别明确，不由记录器擅自触发回零。
4. **保存／丢弃 episode**：开始采样、保存、丢弃使用同一 episode ID 协调本地记录流与
   远端相机；设备各自采集时间独立，不把控制消息同时到达当作硬同步。
   保存时先截断采样范围并等待本地记录持久化确认、所有必需流写队列排空、索引和文件落盘，
   校验连续性后最后发布 episode 的提交标记。只有这个标记存在才进入转换队列。
   活动集使用 `.partial` 或等价状态；异常／断电／缺流不生成完成标记。
   丢弃不进入训练集，按配置保留审计；停止或关网页不会自动保存未确认片段。
5. **远端后台转换**：对已封存的 raw 做只读快照，按会话生成数据集；默认在 session
   结束后排队，也支持手动重试，避免与采集争用 CPU／磁盘。建立可配置目标时间轴，
   state 与 action 保留同一原始记录的对应关系；四路图像及两路力独立匹配并输出误差。
   明确最近帧／等距选较早帧等规则、复用数量和阈值；不通过无限重复旧图伪造采样率。
   映射跨机时钟偏移、漂移与不确定度；不把软件对齐宣传为硬同步。
   必需流超时差／缺失或旋转无效时拒绝发布；预留力未安装是合法的无效掩码状态。
6. **验证并发布**：adapter 产出下表字段，LeRobot API 写入 staging；编码、
   `finalize`、真实 loader 读回和质量检查全部完成后，生成文件清单／大小／SHA-256、
   源 raw 标识、依赖版本和 `READY` 标记，再在同一文件系统内原子发布为不可变 revision。
   质量报告包括采样率、重复／缺失帧、各流误差和时钟不确定度、深度范围、力掩码与数量。
   失败保持原 raw，保留 staging／错误供排查；重试写新目录，不能覆盖已发布数据集。
   转换任务记录 queued/running/failed/ready，重启可恢复，不能仅凭进程退出码宣称数据完整。
7. **LeLab 查看与管理**：只列出已发布的数据集根目录，通过 SSH 页面浏览 episode、RGB、
   状态及支持的深度视图；启动时设置统一数据根目录，避免意外读取默认 HF 缓存。
   自定义深度／力特征若官方页面不能展示，由应用补充查看，不删除真实字段来适配页面。
   编辑／合并产生新 revision，源 raw 与已发布版本不改；首次必须验证合并保留双深度、
   任务、力字段与元数据。Hub 上传或删除不属于当前默认流程，不能自动发布或清理数据。
8. **本地按需拉取**：用户指定 dataset ID／revision，由本地经有线 SSH 使用 rsync
   拉取整个已发布目录（Parquet、视频／深度、meta、报告、校验清单），不是只复制一个 parquet。
   写入本地 `data/lerobot/<dataset_id>/<revision>.partial/`，支持断点续传；
   全部文件按远端清单核对大小和 SHA-256，并用本地兼容 loader 回读后才改为正式目录。
   中断保留 partial 供续传，失败不假报成功；禁止默认 `--delete` 或传完删除远端源数据。
   未完成／正在改写的 revision 不允许拉取。数据传输与预览分离，训练数据不经 MJPEG。
   原始数据只在显式 `--include-raw` 请求时拉取，默认只拉取完整 LeRobot 成品及元数据。

### adapter 与 LeRobot 输出约定

低层运动通道仍使用现有六轴关节目标和夹爪值；adapter 把记录的实际／目标关节经同一
CR7 FK 转成末端 10 维。训练数据采用末端表示不代表可以将 10 维直接传入 SDK。
Robot／Teleoperator adapter 只附着已有 worker，断开只释放客户端；导入、查看数据或转换
不得启动硬件。当前不实现末端模型动作回放／IK，也不为记录新建并行的运动控制链。

| LeRobot 特征／元数据 | 规划输出 |
| --- | --- |
| `observation.state` | float32[10]，实际 TCP＋实际夹爪；names 按前文 pose10 |
| `action` | float32[10]，明确来源的目标 TCP＋目标夹爪；含来源与时间语义说明 |
| `observation.images.cam1_rgb`、`cam2_rgb` | 两路 RGB 视频，由 LeRobot 编码；原始 RGB 无损数据仍保留在 raw |
| `observation.images.cam1_depth`、`cam2_depth` | 两路单通道深度 image，无损保存；参考 agilex 转为米制 float32，并标注 is_depth_map、depth_unit，不能用普通有损视频 |
| `observation.wrench` | float32[12]，两路力／力矩；维度名、传感器、坐标系和单位明确 |
| `observation.wrench_valid` | 两路有效掩码；bool[2] 或锁定版本支持的等价无损表示，必须读回验证 |
| task／instruction | 任务字符串使用该 LeRobot 版本的 task 元数据及索引关联，读回可恢复每帧对应文本 |
| 元数据与审计 | 标定、原始 Z16 depth scale、模型／TCP、原始时间、时钟映射、action 来源与质量报告，随数据集一并传输 |

深度导出到米制 float32 会产生表示舍入，不能宣称与原始 Z16 位级一致；raw 始终保留
原生 Z16。参考版本 loader 可能默认按 mm 返回深度，必须显式检查／设置米制读回，
用 0（无效）、边界值和已知距离测试；不能凭字段名判断单位。
彩色与深度 profile 可不同，分别写 shape／内参，不强行拼成同形状四通道 uint8 图片。

### 本地拟定脚本与验收顺序

以下均为**待实现的入口设计，当前不能作为可用命令运行**；实际实现时同步 CLI、
`config/default.toml`、README 和测试，不在 shell 里复制默认参数：

| 拟定入口 | 用途 |
| --- | --- |
| `scripts/start_dataset.sh` | SSH 按需启动远端接收／数据管理 API，建立 LeLab 隧道；不启动运动 |
| `scripts/stop_dataset.sh` | 停止自有数据服务／隧道；有活动采集或转换时拒绝直接停止，先正常结束任务 |
| `scripts/start_data_record.sh` 新模式 | 集成 session、任务、采样／保存／丢弃及远端完成确认，旧七维入口保持兼容 |
| `scripts/convert_dataset.sh SESSION` | 触发／重试远端转换，查询任务和质量状态；不调用旧 lerobot-converter |
| `scripts/pull_dataset.sh DATASET REVISION` | 经有线 SSH 断点续传成品、校验并在本地发布，可显式附带 raw |

按以下顺序推进，不在文档阶段创建服务或自动部署：

1. 先确定独立包与 raw/schema，使用双 RGBD、EE10 和 12 维力的合成数据完成 adapter、
   LeRobot 写入／读回及 LeLab 浏览测试；保护旧七维和共享 converter 不变。
2. 完成远端原始数据接收、序号去重／重传、跨机时钟映射和 episode 提交协议；
   测试断网、重复包、队列满、磁盘失败、保存中断和进程重启恢复。
3. 实现离线转换任务、质量报告和不可变发布；验证四路图像同步、深度单位、任务文本、
   action 对应关系、力掩码及 LeLab 操作后的特征完整性。
4. 用合成已发布数据验证 rsync 首次拉取、断点续传、篡改校验失败、重复拉取与原数据保留。
   实测有线带宽／磁盘吞吐，不假设网口一定为千兆，也不承诺未测的实时图像吞吐。
5. 最后单独安排现场小段采集验收，再做持续吞吐与跨机同步误差测试。
   新采集所需的运动测试必须由现场人员确认并启动，不因数据部署自动运行跟随或退出返回。

**当前状态**：仅完成本地参考代码阅读和方案编写。未新增上述项目／脚本，未安装远端
LeRobot／LeLab 数据环境，未部署数据服务、执行数据传输或操作任何硬件。
