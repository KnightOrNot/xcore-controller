# 配置参考

controller 默认配置位于 [config/default.toml](../../config/default.toml)。
脚本通过 `tools/config_defaults.py` 读取；优先级为：

```text
显式命令行参数 > 已存在的 XCORE_* 环境变量 > config/default.toml > 脚本内置默认值
```

用 `XCORE_CONFIG=/path/experiment.toml ./scripts/...` 选择另一份 TOML。
未知表、未知字段、非法端口或非正的数值会在执行任何硬件操作前拒绝。

## robot

```toml
[robot]
ip = "192.168.2.160"
follow_max_speed_deg = 75
follow_gripper = true
arm_timeout_s = 20.0
prepare_speed = 4000
remote_stale_timeout_s = 3.0
return_mode = "zero"
```

- `ip`：CR7 控制器地址，不是 Linux 服务机。
- `follow_max_speed_deg`：六轴实时跟随软件限速，必须 `0 < v <= 75`。
- `follow_gripper`：新远端 hardware 角色显式 arm 后同时跟随夹爪，默认 true；
  扳机映射、速度／力来自 SDK 的 `[gripper]`。用远端配置或远端 unit 环境变量
  `XCORE_FOLLOW_GRIPPER` 覆盖，修改后重启服务。本地环境变量不能自动修改远端 unit。
  设为 false 的记录会明确标记夹爪禁用和零占位。
- `arm_timeout_s`：等待 RT 回调和夹爪反馈就绪的最大秒数，范围 1..30，默认 20。
  启动期间保持当前实测关节姿态；失败返回具体错误，不提前宣称 armed。
- `prepare_speed`：启动对齐的 SDK 速度参数（mm/s），与轴速度不是同一量纲。
- `remote_stale_timeout_s`：远端 HTTP 数据桥允许的无新样本时间（0.5..10 s）。
  机器人保持最后目标，超时后停止并锁定；1 s 对跨机 HTTP/GIL 抖动过紧。
- `return_mode`：退出返回目标，取值为：
  - `zero`（默认）：返回六轴 0°；
  - `start`：每次启动跟随／记录前记录当前从臂实际姿态，退出时返回该姿态；
  - `none`：不自动返回，等价于 `--no-return`。

  命令行 `--return-mode` 优先，也可用 `XCORE_RETURN_MODE` 覆盖。`start` 模式的
  启动姿态写入本次会话的 `logs/follow-*/exit_pose.json`；采集失败会在任何运动前中止。
  `zero` 模式在启动前生成零位目标。

## gello

```toml
[gello]
port = "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0"
```

串口是现场值，换机器后必须重新核实。现场标定仍放在
`xcore-sdk-python/config/cr7_calib.json`，不写入本文件。

## remote

```toml
[remote]
gripper_host = "192.168.2.225"
gripper_ssh_user = "rokae"
gripper_port = 5005
camera_ssh_target = "rokae@192.168.2.225"
```

分别对应 `XCORE_GRIPPER_HOST`、`XCORE_GRIPPER_SSH_USER`、`XCORE_GRIPPER_PORT`
和 `XCORE_CAMERA_SSH_TARGET`。SSH 凭据通过已有密钥提供，不写入配置。

## camera

```toml
[camera]
snapshot_dir = "captures"
cam1_url = "http://127.0.0.1:8086"
cam2_url = "http://127.0.0.1:8087"
```

本地截图根目录；最终路径为 `<snapshot_dir>/<cam1|cam2>/<时间戳>/`。
相机端口、设备 profile 和 serve 默认值属于相机项目自己的
`camera-realsense-d435i/config/default.toml`。`cam1_url`/`cam2_url` 是远端角色
访问本机相机服务的 loopback 地址，必须为 `http://127.0.0.1:<port>`；
`XCORE_CAM1_URL`、`XCORE_CAM2_URL` 可覆盖。

## recording

```toml
[recording]
raw_data_root = "data/raw"
lerobot_data_root = "data/lerobot"
dataset_fps = 30
raw_fps = 15
camera_max_frame_age_s = 0.5
convert = true
task = "CR7 GELLO teleoperation"
```

相对路径基于仓库根目录。`dataset_fps` 是转换后的数据集频率，不是控制频率；
`raw_fps` 是远端实时 raw 采样频率（1..60）；`camera_max_frame_age_s` 是机器人样本
可引用的最大相机帧龄，超过即判定该 episode 失败。`convert=false` 等价于
`--skip-conversion`。远端 raw 目录默认是 `$HOME/project/xcore-data/raw`，
可用 `remote-serve --data-root` 覆盖。

## web

```toml
[web]
host = "127.0.0.1"
port = 8095
confirmation_ttl_s = 90
close_grace_s = 8
heartbeat_timeout_s = 120
refresh_hz = 2
```

`host` 只允许 loopback。`confirmation_ttl_s` 是一次性运动令牌有效期（5..600 秒）；
`close_grace_s` 是关闭页面后等待重新心跳的宽限（2..60 秒），`heartbeat_timeout_s`
是浏览器崩溃的兜底（30..600 秒）；`refresh_hz` 是状态轮询频率（0.5..10）。
网页不会另开 SDK、GELLO 串口或相机 pipeline。

## paths

```toml
[paths]
sdk_project = "xcore-sdk-python"
gello_project = "xcore-gello-software"
gripper_project = "xcore-gripper-2F85"
converter_project = "lerobot-converter"
camera_project = "camera-realsense-d435i"
```

用于文档和工具解析；脚本仍以实际 submodule 目录为准。

## timeouts

```toml
[timeouts]
ssh_connect_s = 5
gripper_ready_s = 15
startup_ready_s = 30.0
conversion_wait_s = 600
```

分别对应 `XCORE_SSH_CONNECT_TIMEOUT` 和 `XCORE_GRIPPER_READY_TIMEOUT`。
`startup_ready_s` 对应 `XCORE_STARTUP_READY_TIMEOUT`，是一键入口等待单个服务就绪的
最大秒数（默认 30），相机启动包装命令最多等待两倍时间。未知服务、活动会话、
陈旧 GELLO 数据或未配置的相机无损记录会在进入运动前拒绝。

## 自定义实验

LeLab 浏览地址使用 `[roles].dataset_port`（8090），本地内部 SSH 隧道使用
`[roles].dataset_tunnel_port`（8091，对应 `XCORE_DATASET_TUNNEL_PORT`）；两者不能相同。
网页拉取目的根目录沿用 `[recording].lerobot_data_root`，相对 controller 根目录解析。

```bash
cp config/default.toml config/experiment.toml
XCORE_CONFIG=config/experiment.toml python3 tools/config_defaults.py --json
XCORE_CONFIG=config/experiment.toml ./scripts/start_gello_follow.sh --show-state
```

修改设备地址或限速后，先做只读检查，再进行真机运动验证。

## 子模块配置

各 submodule 有自己的 `config/default.toml`，见
[子模块配置](submodule-config.md)。
