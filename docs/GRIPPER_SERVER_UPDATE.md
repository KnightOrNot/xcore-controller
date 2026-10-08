# 远端夹爪服务部署与管理

夹爪服务系统的有线地址为 `192.168.2.225`，CR7 为 `192.168.2.160`。
服务显示 `0.0.0.0:5005` 表示监听该系统的所有网卡；客户端连接 `.225:5005`。
六轴与夹爪分别控制，统一客户端只读取一次 GELLO。

## 当前现场部署

2026-10-08 已通过 `rokae@192.168.2.225` SSH 完成升级。旧服务仅支持
`activate/status/open/close/move`；新版支持 `follow_status/set_target/stop`，
可以在夹爪运动过程中更新目标，并在目标断流时停止。

本次通过 SSH 传输已发布源码，未使用远端外网或安装新 Python 依赖。
新版在远端原 Conda Python 环境下通过 35 项模拟测试。

| 配置 | 当前值 |
| --- | --- |
| 系统 | Ubuntu 22.04.5，用户 `rokae` |
| Python | `/home/rokae/miniconda3/bin/python3.13`，pyserial 3.5 |
| 夹爪串口 | `/dev/serial/by-id/usb-FTDI_USB_TO_RS-485_DAAQMP8J-if00-port0` |
| 源码提交 | `d250051d8a6e1cf4f77bca3383c9a899be4ad04a` |
| 部署根目录 | `/home/rokae/xcore-gripper-follow` |
| 当前源码链接 | `/home/rokae/xcore-gripper-follow/current` |
| 部署清单 | `/home/rokae/xcore-gripper-follow/deployment.json` |
| 用户服务 | `xcore-gripper-follow.service` |

源码归档解包到 `releases/<提交 SHA>`；该目录不是 Git 工作树，不在部署根目录
执行 `git pull`。后续升级应传输新发布版本，验证后切换服务的源码路径。
原 `/home/rokae/rokae/2F85demo` 文件保持原样，旧服务进程已停止。

服务已设置为随 `rokae` 用户登录启动，由用户级 systemd 在后台管理，
无需保持夹爪启动终端打开。当前 `Linger=no`，未配置用户尚未登录时自动运行。
服务启动／重启会激活夹爪；不要在跟随过程中重启，也不要同时启动旧服务。

## 从控制电脑管理远端服务

控制器入口默认管理远端服务，不会尝试本机 USB：

```bash
./start_gripper.sh                # 启动／检查已安装的用户服务，已有服务不会重启
./start_gripper.sh --status       # 只读检查服务能力及实际反馈
./start_gripper.sh --restart      # 先结束跟随，再重启（会激活夹爪）
./start_gripper.sh --reset-stream # 先结束跟随，停止并清除断流故障
```

远端地址／用户可由 `--gripper-host`、`--ssh-user` 或环境变量
`XCORE_GRIPPER_HOST`、`XCORE_GRIPPER_SSH_USER` 覆盖。
只有明确 `--local --serial-port <实际夹爪串口>` 时才启动本机服务，
该模式会拒绝当前 GELLO 串口及其指向同一设备的别名。

检查服务与近期日志：

```bash
ssh rokae@192.168.2.225 'systemctl --user status xcore-gripper-follow.service --no-pager'
ssh rokae@192.168.2.225 'journalctl --user -u xcore-gripper-follow.service -n 50 --no-pager'
```

需要启动、停止或重启时，先结束当前跟随，再使用对应命令：

```bash
ssh rokae@192.168.2.225 'systemctl --user start xcore-gripper-follow.service'
ssh rokae@192.168.2.225 'systemctl --user stop xcore-gripper-follow.service'
ssh rokae@192.168.2.225 'systemctl --user restart xcore-gripper-follow.service'
```

## 在控制电脑上验证并跟随

先只读检查服务：

```bash
cd /home/knight/projects/xcore/xcore-controller
./xcore-sdk-python/.venv/bin/xcore-sdk-python gripper-check --gripper-host 192.168.2.225
./start_gello_follow.sh
```

检查输出应有 `ok: true`、`streaming: true`、`stream_error: null` 和实际
`position_raw`。默认脚本预览输出启动偏差与夹爪连接状态；
需要查看连续关节角和 `gripper_target` 时使用 `./start_gello_follow.sh --show-state`。
这些只读检查不发送运动目标。

再保持 GELLO 在期望姿态，启动统一跟随：

```bash
./start_gello_follow.sh --enable-motion
# 单独设置实时关节限速
./start_gello_follow.sh --enable-motion --max-speed-deg 10
```

脚本默认使用 `.225:5005`、启动对齐 SDK 速度 `4000 mm/s`，
实时跟随速度上限默认 `75°/s`，可独立由 `--max-speed-deg` 指定。
默认不循环打印状态。输入 `y` 后先对齐六轴，
随后从同一个 GELLO 读取进程发送六轴目标和独立夹爪目标。Ctrl+C 结束跟随。

## 验证范围

已验证远端服务升级、真实激活与位置反馈、实际 `set_target` 当前位置保持及
`stop` 通信，控制器只读预览同时读取 GELLO 六轴和 ID7 扳机。
当前位置保持测试未改变开合目标，未发送 CR7 运动命令。
夹爪全行程随扳机开合及更快启动对齐仍需实际跟随实验验收。
本机日志保存于 `logs/gripper-follow-preview-20261008.log` 和
`logs/gripper-stream-hold-20261008.json`，不纳入 Git。
