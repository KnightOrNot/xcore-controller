# xcore-controller

用 GELLO 主臂遥操作 ROKAE CR7 从臂和 Robotiq 2F-85 夹爪，并把双臂相机、夹爪、
末端位姿一起录成 LeRobot 数据集。

**本地只负责主臂输入和操作界面**（GELLO 串口服务、网页／终端面板、数据拉取）；
**CR7 实时控制、双 D435i 采集、数据封存与转换、LeLab 浏览都在远端 Linux 主机**完成。
本地与远端之间只有有线网络 + SSH。

## 现状

| 已验证 | 仍需现场验收 |
| --- | --- |
| 本地 GELLO 七通道、远端 RT 跟随（小幅动作、零位移启停） | 大范围轨迹跟随 |
| 双 RGBD 无损记录、会话封存与提交协议 | 断流停止的真实表现 |
| 远端 LeRobot 转换发布、LeLab 浏览、本地拉取与 SHA-256 校验 | 退出返回、下电、关闭网页后的自动收尾 |
| 网页数采面板、按键入口、数据表示切换（pose10／joints） | 新远端的完整部署流程 |

“代码已实现”“离线测试通过”“真机已实测”是三件不同的事，需要区分标注。历史实施记录见
[操作手册](docs/OPERATIONS.md) 与 [docs/HISTORY.md](docs/HISTORY.md)。

## 组成

| 仓库 | 职责 |
| --- | --- |
| `xcore-controller` | 顶层入口：脚本、配置、本地／远端双角色、网页面板、拉取 |
| `xcore-sdk-python` | CR7 SDK 封装、限位、实时跟随、末端 FK |
| `xcore-gello-software` | 本地 GELLO 串口只读采集 |
| `xcore-gripper-2F85` | Robotiq 2F-85 协议与夹爪服务 |
| `camera-realsense-d435i` | 两台 D435i 的采集、预览、无损记录 |
| `xcore-adapters` | 数据契约、字段映射、GELLO／机器人适配 |
| `xcore-dataset` | raw 封存、时间对齐、LeRobot 转换、LeLab 服务 |
| `lerobot-converter` | 共享的旧七维转换器（本链路不使用，保留兼容） |

## 快速开始

### 0. 前提

- 控制电脑：`git`、`pyenv`、`uv`，Python 3.11.16 与 3.12.14（`pyenv install -s`）
- 远端主机：**已完成部署**（见[远端部署](docs/remote-deploy.md)），本地能用密钥 `ssh` 登录
- 现场：GELLO 接本地 USB；CR7（`192.168.2.160`）、夹爪、两台 D435i 接远端

### 1. 克隆

```bash
mkdir -p "$HOME/projects/xcore" && cd "$HOME/projects/xcore"
git clone https://github.com/KnightOrNot/xcore-controller.git
cd xcore-controller
# .gitmodules 用 SSH URL；没有配置 GitHub SSH 时临时改用 HTTPS
git -c url."https://github.com/".insteadOf=git@github.com: submodule update --init
```

### 2. 初始化环境

```bash
./scripts/setup.sh            # 建 5 个独立环境并自检，不连接硬件
```

### 3. 自检（不碰机械臂）

```bash
./scripts/setup.sh --check-only
./xcore-sdk-python/.venv/bin/xcore-sdk-python doctor   # 应返回 hardware_connected: false
./scripts/start_remote_record.sh --check-only          # 启动并检查全部服务，不激活、不动
```

### 4. 第一次真机

标定文件已随仓库提供（**仅适用于 192.168.2.160 这台 CR7**，换机器必须重新标定，
见 [操作手册 · 首次标定](docs/OPERATIONS.md#6-首次标定建立主臂与从臂的对应关系)）。

确认场地安全、急停可达后：

```bash
./scripts/start_remote_record.sh --task "pick and place" --web --enable-motion
```

它会启动全部远端服务、打开 `http://127.0.0.1:8095` 面板；真正的运动要你在网页上
勾选确认并点“启动跟随”。自动化采集用终端模式（去掉 `--web`），会先要一次 `y` 确认。

按 `Ctrl+C`、面板 `Q`、或直接关闭网页，都会丢弃未保存片段、按 `return_mode` 返回、
下电，并停止本次启动的远端服务（`--keep-services` 可保留）。

### 5. 日常

```bash
./scripts/start_remote_record.sh --task "任务描述" --web --enable-motion
```

## 基本配置

唯一配置源是 `config/default.toml`；脚本通过 `tools/config_defaults.py` 读取，不要在
命令行或代码里另写一份默认值。

优先级：**命令行参数 > 已存在的 `XCORE_*` 环境变量 > `config/default.toml` > 内置默认值**。
用 `XCORE_CONFIG=/path/experiment.toml` 换一整份配置。

| 表 | 关键项 | 说明 |
| --- | --- | --- |
| `[robot]` | `ip`、`return_mode`、`follow_max_speed_deg`、`follow_gripper` | CR7 地址、退出返回（`zero`／`start`／`none`）、软件限速（≤75°/s）、是否跟随扳机 |
| `[gello]` | `port` | 主臂 FTDI by-id 串口，换机器要重新核实 |
| `[remote]` | `gripper_host`、`camera_ssh_target`、`gripper_port` | 远端主机与夹爪 TCP 端口 |
| `[recording]` | `raw_data_root`、`lerobot_data_root`、`raw_fps`、`task` | 本地数据根、采样频率、默认任务名 |
| `[web]` | `host`、`port` 8095、`close_grace_s` | 面板只监听 loopback；这几个值决定关页面后多久自动收尾 |
| `[roles]` | 各端口、`remote_python`、`remote_data_root` | 远端运行环境与数据根（`~/project/xcore-data`） |
| `[timeouts]` | `startup_ready_s`、`conversion_wait_s` | 服务就绪与等转换发布的上限 |

完整字段、取值范围和覆盖变量见 [配置参考](docs/reference/config.md)。

常见覆盖：

```bash
XCORE_RETURN_MODE=none ./scripts/start_remote_record.sh --task "调试" --check-only
./scripts/start_remote_record.sh --task "pick" --web-port 8096
```

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `./scripts/start_remote_record.sh --task T [--web] [--enable-motion]` | 一键数采（默认入口） |
| `./scripts/start_remote_record.sh --check-only` | 只启动并检查服务 |
| `./scripts/start_remote_controller.sh --hardware` | 只起远端运动角色与隧道 |
| `./scripts/start_gripper.sh` / `stop_gripper.sh` | 远端夹爪服务启停 |
| `./scripts/start_camera.sh` / `stop_camera.sh` | 两台相机预览、截图、启停 |
| `./scripts/start_dataset.sh` / `stop_dataset.sh` | LeLab 浏览与网页拉取网关 |
| `./scripts/pull_dataset.sh [--pose\|--joints\|--list] ID REV` | 按表示拉取已发布数据集 |
| `./scripts/convert_dataset.sh` | 触发／重试远端转换 |

全部参数见 [CLI 参考](docs/reference/cli.md)。

## 远端部署

远端需要源码副本、独立的 Python 运行环境和 5 个 systemd 用户 unit，且**不需要**在
远端联网安装依赖。完整步骤、目录布局与版本清单见
**[远端部署](docs/remote-deploy.md)**。

换到新现场时，除部署外还要改：`[robot].ip`、`[remote]` 的主机、`[gello].port`、
相机 `deploy/camN.json` 的序列号、夹爪 RS485 by-id，并重新做一次标定。

## 数据与安全

- 所有服务默认 `disabled`，**不开机／登录自启**，由脚本按需 `systemctl --user start`。
- 运动永远要显式授权：`--enable-motion` 只是允许，网页还要再确认一次；不加就只能看状态。
- 口令、SSH 私钥、数据集、日志、`.venv` 不进 Git（现场标定与相机序列号已按用户要求纳入）。
- 采集数据在远端 `~/project/xcore-data/`，本地拉取落在 `data/lerobot/`，均被 Git 忽略。
- 客户端超时**不等于**远端已取消：先查 `status` 和实测位姿，不要重复发运动命令。

## 文档

| 内容 | 位置 |
| --- | --- |
| 详细操作手册（安装、接线、标定、跟随、排障） | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| 文档总索引 | [docs/index.md](docs/index.md) |
| 远端部署 | [docs/remote-deploy.md](docs/remote-deploy.md) |
| 配置／CLI／错误码 | `docs/reference/` |
| 数据契约与设计 | [docs/DATASET_EE10_DESIGN.md](docs/DATASET_EE10_DESIGN.md) |
| 协作与交接约定（给 AI／同事） | [AGENTS.md](AGENTS.md)、[docs/HISTORY.md](docs/HISTORY.md) |
