# CLI 参考

所有 controller 入口位于 `scripts/`，会根据脚本位置解析仓库根目录，因此可以从
任意工作目录调用。默认参数来自 `config/default.toml`；命令行参数优先。

## controller 脚本

| 命令 | 行为 |
| --- | --- |
| `./scripts/setup.sh [--check-only] [--skip-submodules]` | 初始化子模块与五个 Python 环境 |
| `./scripts/start_gello_follow.sh [选项]` | 只读预览或真实六轴＋夹爪跟随 |
| `./scripts/start_data_record.sh [选项]` | 跟随并记录从臂反馈，退出后转换 |
| `./scripts/start_remote_record.sh --task TEXT --enable-motion` | 一键启动 GELLO／控制器／夹爪／双 RGBD／LeLab 及连接，确认后进入数采 |
| `./scripts/start_remote_record.sh --web [--enable-motion]` | 启动本地网页数采面板；不加 `--enable-motion` 为只读 |
| `./scripts/pull_dataset.sh [--pose|--joints] ID REV` | 按表示拉取已发布版本；`--list` 列出发现项 |
| `./scripts/start_gripper.sh [选项]` | SSH 按需启动远端夹爪服务；`--status` 只读 |
| `./scripts/stop_gripper.sh` | 完全停止远端夹爪服务（跟随锁占用时拒绝） |
| `./scripts/start_camera.sh [preview|connect|start|stop|status|info|snapshot|disconnect]` | 双 D435i 管理 |
| `./scripts/stop_camera.sh [--camera all|cam1|cam2]` | 停止远端相机 API 并清理隧道 |

`uv run xcore-controller watch-motion http://127.0.0.1:9012` 用于监测已启动的远端跟随；
检测到 stopped／unarmed／不可达时打印原因并非零退出。远端数采脚本自动管理它。
正常 Q 按 return_mode 返回，健康监测发现故障时停止会话、不自动返回姿态。

远端数采入口默认自动准备服务；`--check-only` 只启动并检查，不激活、不对齐、不 arm。
`--no-auto-start` 用于已有全部服务的手动调试。`--no-prepare` 跳过 NRT 对齐，arm 仍检查门限。
`--web` 不进入终端 R/S/D 流程：页面通过同一远端 API 执行，长操作在后台任务中运行；
`--web-port` 覆盖 `[web].port`。运动按钮另需服务端一次性确认令牌。
一次现场 `y` 确认涵盖夹爪按需激活、对齐与跟随。Q 会结束本次自建的本地后台连接，
远端服务仍按需待命，供后台转换和下次使用。

### start_gello_follow.sh

默认不授权运动。关键参数：

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--show-state` | 只读打印每个周期的状态 |
| `--enable-motion` | 显式授权真实跟随（需现场确认） |
| `--arm-only` | 只跟随六轴，不连接夹爪 |
| `--max-speed-deg` | `config` 中 `robot.follow_max_speed_deg`，上限 75 |
| `--prepare-speed` | 启动对齐 SDK 速度参数（mm/s），默认 4000 |
| `--return-mode start\|zero\|none` | 退出返回目标；默认取 `robot.return_mode`（`zero`） |
| `--no-return` | 禁止退出返回运动，等价于 `--return-mode none` |

`zero` 模式使用六轴 0° 目标。`start` 模式在启动对齐前读取当前从臂六轴反馈，
写入本次会话的 `logs/follow-*/exit_pose.json`；Ctrl+C、SIGTERM、正常结束和故障退出
都返回该姿态。只读预览不返回。固定姿态文件仍可直接用 `xcore return-pose --pose-file`
执行，但不再属于启动器模式。

### start_data_record.sh

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--task TEXT` | `recording.task`，非空 |
| `--dataset-fps N` | `recording.dataset_fps`，默认 30 |
| `--raw-data-root PATH` | `recording.raw_data_root` |
| `--lerobot-data-root PATH` | `recording.lerobot_data_root` |
| `--skip-conversion` | 只保存 raw |
| `--gripper-host HOST` | 远端夹爪主机 |
| `--start-recording` | 对齐后立即开始 episode |
| `--return-mode` / `--no-return` | 与跟随入口相同 |

R 开始、S 保存、D 丢弃、P 状态、H 帮助。未保存片段保留 `.partial`。
其余跟随参数原样传给统一入口。退出返回模式默认同样取 `robot.return_mode`
（`zero`）；`start` 模式在记录开始前采集姿态，退出时返回该姿态。

### start_gripper.sh / stop_gripper.sh

- `--status` 只读检查 TCP 服务，不启动或重启。
- `--restart` 会先确认没有跟随任务，再重启远端服务；重启可能激活夹爪。
- `--reset-stream` 清除断流超时锁定；`--local --serial-port PATH` 使用本机串口。
- stop 持有与跟随相同的 `.follow.lock`；跟随运行时拒绝停止。

## 网页面板的 HTTP 接口

本地 loopback，仅用于页面自身：`GET /api/state`、`POST /api/confirmation`、
`POST /api/action/{start|stop|record-start|record-save|record-discard|finish}`。
POST 要求同源 JSON；`start`／`finish` 需要一次性 `token`。页面刷新/关闭不会触发操作。

## 数据拉取

`pull --pose` 要求 pose10，`--joints` 要求关节表示 `[q1..q6,g]`；两者互斥。
旧 `pull ID REV` 等价于 `--pose`。拉取后校验 `representation.json`（旧版本按
observation.state 维度推断），不匹配时保留 `<rev>.partial/` 并报错。

## SDK CLI

```bash
uv run --project xcore-sdk-python xcore --help
uv run --project xcore-sdk-python xcore status --config config/experiment.toml
```

主要命令：

| 命令 | 行为 |
| --- | --- |
| `doctor` | 离线检查 Python、SDK 二进制和 API；不连接硬件 |
| `status` / `info` / `joints` / `limits` / `monitor` | 只读反馈 |
| `follow-server` / `follow` | 跟随服务与主臂客户端 |
| `follow-prepare` / `return-pose` | 启动对齐与退出返回 |
| `follow-check` / `follow-calibrate` | 只读检查与现场标定 |
| `movej` / `move-joint` | 有界关节运动（需显式调用） |
| `network check|configure|reset` | 有线网络诊断与临时地址 |
| `gripper-check` | 只读夹爪反馈 |

全局选项包括 `--ip`、`--local-ip`、`--timeout`、`--sdk-dir`、`--config`。
`--config` 可放在子命令前或后。

## 夹爪 CLI

```bash
uv run --project xcore-gripper-2F85 xcore-gripper-2f85 --config config/default.toml status
uv run --project xcore-gripper-2F85 xcore-gripper-2f85 move --closure 0.4
```

位置约定：`pos=0` 全开，`pos=255` 全闭；`closure=1` 全闭。服务端：

```bash
xcore-gripper-2f85-server --config config/default.toml
```

`--config` 是 TOML 默认值文件；`--serial-port` 显式指定 RS485 串口，
空值表示自动检测。

## 转换器

```bash
lerobot-converter/.venv/bin/python tools/convert_cr7.py SESSION OUTPUT \
  --repo-id local/demo --fps 30
lerobot-converter/.venv/bin/python -m lerobot_converter SESSION OUTPUT --config config/default.toml
```

controller 的 `start_data_record.sh` 会自动调用 CR7 适配转换脚本；转换失败
不影响已保存的 raw。

## 相机 CLI

```bash
camera-realsense-d435i --camera cam2 status
camera-realsense-d435i --camera cam2 snapshot --output captures/cam2/demo
camera-realsense-d435i serve --config ~/.config/camera-realsense-d435i/cam2.json --port 8087
```

`--defaults PATH` 选择相机项目的 TOML 默认值文件；serve 的 `--config` 仍是
每台相机的现场 JSON，不与 TOML 默认值混用。

## 退出码

正常完成、人工取消且清理完成返回 0；应用或清理错误返回 1；参数语法错误返回 2；
非托管操作被中断返回 130。转换子进程的失败码原样返回。
