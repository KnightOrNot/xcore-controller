# xcore-controller 协作说明

本文用于让后续 AI 接手工程。先阅读本文、`README.md` 和将要修改的子项目文档；
以代码、现场配置和实际测试结果为准，不能将历史日志或计划当作已验收功能。
最后更新：2026-10-21。双相机第一版已部署并通过硬件采集测试，验收边界见文末。

## 用户目标和工程边界

- 将 GELLO 主臂六轴和扳机映射到 ROKAE xMate CR7 从臂及 Robotiq 2F-85 夹爪，
  通过一个顶层 `.sh` 完成日常启动。无需 ROS2、MoveIt 或仿真跟随启动链。
- 工程结构、独立子项目、CLI 和脚本组织参考相邻 `agilex*` 项目；
  CR7 驱动接口、实时运动方法参考相邻 `gello for CR7` 项目。不要将后者整个工程照搬。
- 实现从臂反馈数据记录、片段保存及 LeRobot 数据转换；相机项目负责采集、信息和预览，
  数据集转换属于独立转换项目。
- 新增远端两台 RealSense D435i 的启停、信息读取、RGB＋深度实时预览及截图。
  在本地发命令，通过 SSH 管理远端服务并在本地浏览器查看画面。
- **当前任务不要移动机械臂，不要启动跟随或执行退出返回。** 相机开发与真机控制解耦。

## 仓库布局与 Git 规则

```text
xcore/
├── xcore-controller/              # 集成仓库：脚本、文档、工具、测试、submodule 指针
│   ├── scripts/                  # 所有 controller shell 命令：setup/start/stop
│   ├── xcore-sdk-python/          # CR7 SDK 封装、RT 跟随、记录；独立 Git 子模块
│   ├── xcore-gello-software/      # GELLO 只读采集和标定支持；独立 Git 子模块
│   ├── xcore-gripper-2F85/        # 夹爪驱动、协议、服务源码；独立 Git 子模块
│   ├── lerobot-converter/         # 独立转换环境；独立 Git 子模块
│   └── camera-realsense-d435i/    # 新增独立相机仓库的 submodule
└── camera-realsense-d435i/        # 独立相机开发 checkout
```

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
原始数据 `data/raw/`，转换结果 `data/lerobot/`；未保存片段保留 `.partial`。
记录的是从臂反馈，不能用目标角冒充实际角。故障恢复和退出返回不写进 episode。
参考 `docs/DATA_RECORDING.md` 与 `tools/convert_cr7.py`。
转换使用独立 Python 3.12 环境，不能把转换依赖塞入控制 SDK 环境。

## 远端双 D435i：当前实现

用户已确认需要**两台相机**，各自 RGB＋深度页面；第一版包括远端服务启停、设备信息、
本地实时预览和截图，不要求 ROS2，也尚未要求 IMU 采集或录像接入数据记录。

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

数据语义：预览深度伪彩 JPEG 仅用于查看，截图另存原始 Z16 无损 16 位 PNG、
depth scale、各流内参、外参、独立帧号和时间戳及 timestamp domain。
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
  集成安装脚本的子模块数量需随相机接入更新。
- 根据修改范围运行父仓库／相应子模块 pytest 和 Ruff，不要为检查文档而启动硬件。
  SDK 离线检查为 `uv run --project xcore-sdk-python xcore doctor`。
  父仓库测试使用 `./lerobot-converter/.venv/bin/python -m pytest tests -q`，
  其中转换测试需要转换项目依赖，不能直接拿缺少该包的 SDK 环境运行全部父仓库测试。
- 不在现有跟随会话运行时发起另一个 SDK 连接；不要自动发起运动测试。
- 相机测试至少覆盖启动／停止／重启、断流与异常传播、原始深度格式、双机同时预览。
  实测帧率、USB 模式、截图和测试结果写入相机 README；未测试项明确标记。
- 不要记录或提交登录密码、SSH 私钥和本地敏感画面；保留现场配置与业务数据。
- 默认只提交当次任务范围；用户明确要求提交全部项目改动时，先审阅父仓库及各子模块，
  排除现场配置／数据，再按子仓库到父仓库的顺序提交。
- 功能或部署状态变化后更新本文，写清“代码已实现”“离线测试通过”“硬件已实测”的区别。

**本次交接状态**：相机项目已推送到新仓库 main，提交
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
双机硬同步、IMU、连续录像和机械臂数据记录接入仍未实现，需用户明确后再扩展。

2026-10-21 用户要求将当前全部项目改动 commit。SDK 的共享限位、拒绝启动错误传播、
保存姿态返回及配套测试／文档已提交为 `1d8474d`。
控制仓库将相机子模块、统一 scripts 入口、停止服务脚本、文档和测试一并纳入本次本地提交，
固定上述 SDK 版本。本次未执行 push；后续发布必须先推送 SDK，再推送控制仓库。
现场标定、退出姿态 JSON、日志、数据、虚拟环境仍不纳入 Git。

## Controller 脚本入口

用户要求 controller 自身所有 `.sh` 放在 `scripts/`，根目录不保留旧入口。
五个原入口已迁移，脚本都根据自身位置解析仓库根目录，支持从其他工作目录调用。
子模块拥有的脚本保留在各自仓库，不能跨 Git 边界搬动。

- `scripts/setup.sh`、`scripts/start_gello_follow.sh`、`scripts/start_data_record.sh`。
- `scripts/start_gripper.sh` 按需启动；`scripts/stop_gripper.sh` 完全停止远端服务。
  后者持有与跟随相同的 `xcore-sdk-python/.follow.lock`；占用时拒绝 SSH stop。
- `scripts/start_camera.sh` 按需启动；其 `stop` 子命令仅停止采集，API 保留。
  `scripts/stop_camera.sh` 完全停止远端 API 并清理对应隧道，默认两台，支持 `--camera cam1|cam2`。
  远端 stop 失败时保留隧道，不假装成功。
- 停止入口的验证使用隔离的 SSH／CLI stub，不应为了测试脚本而终止用户正在使用的服务。

本次迁移验证：父仓库 34 项离线测试通过，新增测试覆盖夹爪占锁拒绝停止、
相机单台／双台选择、SSH 失败时保留隧道及非法参数在 SSH 前拒绝；
七个脚本的 shell 语法和帮助通过，五环境检查通过。未执行真实远端 stop。
SDK 完整离线测试 200 项通过，Ruff 检查通过；controller 离线测试 34 项通过。
这些结果不替代现场运动验收，本次提交过程中未连接或操作机械臂。
