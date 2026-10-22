# 远端数据链首阶段（2026-10-22）

本次完成硬件只读检查、controller 双角色基础、远端 SDK 只读 worker、GELLO 数据桥，
以及独立数据项目的合成 raw → LeRobot → LeLab → 本地拉取闭环。
**尚不能用新链路启动真实跟随或采集真机训练数据。** 旧跟随入口仍保持原实现。
后续阶段（远端运动、FK、多流 raw、转换队列、本地数采入口）的实现与验证状态见
`AGENTS.md` 的“数采全流程实施检查点”；本文保留首阶段硬件与部署记录。

## 硬件检查

| 设备 | 实测结果 |
| --- | --- |
| 本地 GELLO | FTDI FTB4C7PQ，57600；ID1～7 全部在线，实际位置可读，torque=0 |
| 远端 SSH | rokae@192.168.2.225 正常，有线网口报告 1000 Mbps |
| CR7 | 本地和远端 Python 3.11 SDK 0.7.1 均连接成功，六轴、型号、位姿可读；远端 local_ip=.225 |
| CR7 当前模式 | manual、power off、idle；本次没有上电、发运动目标或执行返回姿态 |
| 夹爪 | 实际 RS485 为 DABGMMQO；旧手动服务不支持 follow_status，已替换为已有项目的连续跟随服务 |
| 夹爪反馈 | status_code=249、position_raw=3、position_mm=49.41、moving=false、streaming=true、stream_error=null |
| D435i cam1 | 349522071221，USB 2.1；640×480 RGB uint8＋深度 uint16 |
| D435i cam2 | 349522072318，USB 2.1；640×480 RGB uint8＋深度 uint16 |
| 双机同时采集 | 10 秒各推进 150 帧，约 15 FPS；深度非零比例约 86.0%／80.5%，随场景变化 |
| 两路力 | 本次仍是字段预留，未确认设备／接口，不冒充已读到实测力 |

夹爪原手动进程来自 `~/rokae/2F85demo`。确认反馈未运动后停止了该进程，
将已有用户 unit 的串口从 DAAQMP8J 改为 DABGMMQO，并以 `--no-activate` 启动，
没有重新激活或执行开合。原 unit 备份在
`~/.local/state/xcore-gripper-migrations/20261022-readonly-service/`。
unit 仍 disabled。之后夹爪若断电／复位而未激活，需显式激活，不能认为启动 API 已完成激活。

## 已有入口与使用范围

首次在当前 checkout 安装轻量 controller 环境：`uv sync --python 3.11`。
`xcore-adapters/` 和 `xcore-dataset/` 已绑定 GitHub 并作为同名 submodule 引入。
克隆后先 `git submodule update --init`；新数据工具环境另执行
`uv sync --project xcore-dataset --python 3.12 --extra dataset --extra app`。
旧 `scripts/setup.sh` 仍只安装原有五个子项目环境，不负责上述新环境。
新命令目前按完整 checkout 运行，不支持脱离工程资源的单 wheel 独立部署。

三个终端分别运行：

```bash
./scripts/start_gello_service.sh
./scripts/start_remote_controller.sh --hardware-read-only
uv run xcore-controller bridge --leader-url http://127.0.0.1:9011 --remote-url http://127.0.0.1:9012
```

检查远端：

```bash
uv run xcore-controller status http://127.0.0.1:9012
```

能看到远端 SDK 状态及 `leader_sequence` 推进；`motion_capable=false`。
`arm` 在硬件模式被拒绝，不能将这条数据桥当作已经完成的远端运动控制。
仅测试模拟接收时用 `--simulate`，不会连接 CR7。
远端只读 SDK 会话存续期间不要另开本地 SDK 会话；本地 GELLO 服务也会持有原跟随锁。
桥退出后接收状态超时锁定，恢复数据不会自动 arm；这证明接收状态机，不代表真机停止行为已验收。

远端数据浏览与下载：

```bash
./scripts/start_dataset.sh
# 浏览器打开 http://127.0.0.1:8090/edit-dataset
# 另一终端按需拉取本次合成测试数据：
./scripts/pull_dataset.sh synthetic-check-20261022 rev-0001
```

本次远端实际转换并读回 12 帧合成双 RGBD 数据，LeLab 成功列出一段 episode，
本地成功拉取全部文件、校验 SHA-256 并用真实 loader 回读。重复拉取不会覆盖已有成品。
本地位置 `data/lerobot/synthetic-check-20261022/rev-0001/`，明确是合成数据，不用于训练。

结束本地 bridge 和 GELLO 后停止远端服务：

```bash
./scripts/stop_remote_controller.sh
./scripts/stop_dataset.sh
```

启动脚本通过 systemd 按需启动，再维持前台 SSH 隧道；Ctrl+C 只结束该隧道，
远端 unit 通过上述停止入口结束。所有新 unit 均 disabled，不开机／登录自启。
此阶段数据 unit 仅提供浏览，转换是单独 CLI，不提供采集／任务调度 API。

## 远端部署现状

远端 SDK 只读环境为 `~/project/xcore-runtime/cpython-3.11.16-linux-x86_64-gnu/`，
配套 vendor311；数据环境为同目录下独立 Python 3.12.14＋`dataset-venv/`。
相机原有 Python 3.13 环境未改动。
源码部署为当前工作区快照，不是已经发布的 Git 版本。

数据环境按照本地 `xcore-dataset/uv.lock` 的 CPU 依赖复制到远端，并修正两个本地包的 pth
为远端源码路径。远端 conda 获取 FFmpeg 时遇到证书错误，未关闭 TLS 校验；
现使用锁定 PyAV 15.1.0 自带的 FFmpeg 7 共享库，在独立 `xcore-runtime/media/lib/`
建立 SONAME 别名，TorchCodec 0.11.1 实际加载／解码通过。
`media/bin/ffmpeg` 为 imageio-ffmpeg 提供的静态 7.0.2 二进制；PATH／LD_LIBRARY_PATH
仅在数据服务环境设置，没有替换系统库或修改相机环境。
该离线部署尚未自动化为完整安装器，后续应生成带清单和版本的部署包，不能假设 rsync 一个 venv
即可换机器运行。`deploy/install_role_services.py` 只安装 disabled 的用户 unit，不安装运行依赖，
已存在 unit 时拒绝覆盖，需审查版本后更新。

## 验证和剩余工作

当前 controller 55 项测试通过，adapter／dataset 合计 7 项测试通过，Ruff 和新脚本语法通过。
覆盖了真实 LeRobot writer/loader、双深度边界值／单位、12 维力、掩码／中文任务、
partial／篡改／超时拒绝、HTTP 接收锁定、硬件 arm 拒绝和设备锁。
这些结果不代表真机运动或长时间吞吐验收。
两个独立包 wheel 构建通过，dataset 默认 TOML 已核实包含在 wheel 中。
测试结束已关闭本地 GELLO／数据桥和 SSH 测试隧道，远端只读／模拟 controller、
数据浏览与相机 unit 均停止且 disabled；夹爪保留修复后的服务运行，未运动。

下一阶段按 AGENTS.md 继续：

1. 远端 SDK worker 接入现有经过测试的实时驱动，落实主臂映射、限位、对齐、断流停止与退出策略。
2. 验证实际 CR7 的 FK 和夹爪 TCP；本次只确认 vendor 六轴模型 API 可用，未验收工具标定。
3. 相机单 pipeline 增加原始 RGB／Z16 记录分支；不能使用当前 JPEG 预览来生成无损 raw。
4. 真实多流 raw 接入、跨机源时间／设备时钟映射、session 多 episode 协调和转换任务恢复。
5. 完善 LeRobot Robot／Teleoperator adapter、部署包及长时间回归；最后安排运动验收。

用户本轮收尾要求为绑定两个 GitHub 仓库、注册 submodule、记录进度后 commit／push 并停止。
后续开发待新指令；没有继续实现运动控制或真实多流录制。
