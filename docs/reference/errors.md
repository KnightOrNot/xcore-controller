# 故障排查

## 配置被拒绝

`unknown configuration sections` 或 `unknown <section> options` 表示 TOML
表名或字段拼写错误。端口必须是 1..65535，频率、超时和步长必须为正且有限，
`follow_max_speed_deg` 不能超过 75。修正后先用：

```bash
python3 tools/config_defaults.py --json
```

## 找不到命令或库

从仓库根目录执行 `./scripts/setup.sh`；`--check-only` 只检查。controller 脚本
不激活子项目环境，而是调用各项目的 console script 或 `.venv/bin/python`。
路径移动后重新创建对应环境，不要修补旧 shebang。

## 串口不存在或无权限

检查 `/dev/serial/by-id/` 与 `[gello].port`，确认供电、57600 波特率和
`dialout` 组权限（加入组后需重新登录）。同一串口只允许一个采集进程。

## 跟随锁被占用

`another workflow is running` 或 `.follow.lock` 占用表示已有跟随／退出返回任务。
先正常退出旧流程；锁文件存在本身不代表被持有，不要删除锁文件绕过。

## 启动误差或限位失败

核对现场标定、主从方向和主臂姿态。历史上的 J1 +183.5°、J6 +176.7° 报错是
限位问题，不能通过删除检查、自动截断或无条件 ±2π 包装“修复”。恢复后先只读
检查反馈。

## 退出没有回到零位

这是预期行为。返回目标由 `[robot].return_mode` 决定：默认 `start` 返回本次启动前
记录的实际姿态；`saved` 返回固定姿态文件；只有 `zero` 才回六轴 0°。
`none`／`--no-return` 不返回。新 clone 在 `saved` 模式下没有有效姿态文件时应明确报错，
而不是静默退回零位。

## 返回模式无效或采集姿态失败

`返回模式必须是 start、saved、zero 或 none` 表示 `--return-mode` 或
`XCORE_RETURN_MODE` 拼写错误，会在任何硬件操作前退出。
`start` 模式在启动对齐前调用 `xcore capture-pose`；如果 CR7 不可达、反馈不足六轴
或会话被占用，会在运动前中止，不会退回零点。先只读检查 `xcore status` 和
`xcore joints`，再重试。

## 保存后没有数据集

只有按 S 保存的 `episode_*.jsonl` 才会转换；活动片段在 Ctrl+C 时保持
`.partial`，转换器忽略它。检查转换器 3.12 环境、磁盘空间和目标目录是否已存在
（转换要求目标目录尚不存在）。raw 不会被删除，可稍后手工转换。

## 相机无法连接

- 先看远端服务：`systemctl --user status camera-realsense-d435i@cam1.service`。
- 端口没有监听时，本地 `connect`/`preview` 会按需 SSH 启动。
- 设备未枚举：检查 USB、udev 权限和序列号是否与 JSON 一致。
- 多设备时必须显式序列号；两台不能共用端口。
- 关闭网页不会停止采集；需要显式 stop。

## 相机画面或深度异常

预览深度是伪彩 JPEG，不能用于测量。截图保存原始 Z16；零表示无效深度。
没有对齐时 RGB 与深度像素不一一对应。cam2 曾出现画面贴近遮挡物、深度非零
约 1%，应先检查朝向、遮挡和距离，而不是升级固件。

## 夹爪服务无法启动

先确认 RS485 适配器插在远端服务机上：

```bash
ssh rokae@192.168.2.225 'lsusb | grep -i ftdi; ls -l /dev/serial/by-id/'
```

适配器不在位时服务会退出并 `auto-restart`；此时应先停止服务，而不是反复重启。
夹爪串口不能与 GELLO 主臂串口混用。

## SSH 或远端操作失败

确认 `XCORE_CAMERA_SSH_TARGET` / `XCORE_GRIPPER_HOST` 和密钥。停止脚本在远端
失败时保留隧道并返回非零，不假装成功。不要在跟随运行期间重启远端服务。
