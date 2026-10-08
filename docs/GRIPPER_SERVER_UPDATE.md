# 远端夹爪服务升级

当前夹爪服务系统的有线地址为 `192.168.2.225`，CR7 为 `192.168.2.160`。
服务显示 `0.0.0.0:5005` 表示监听该系统的所有网卡；客户端连接 `.225:5005`。

2026-10-08 的只读检测已确认远端 TCP 服务可达、夹爪已激活，实际
`position_raw=3`。远端仅支持 `activate/status/open/close/move`，缺少连续目标
更新、反馈能力检查和停止指令，因此不能用于当前统一跟随。
以下升级尚需在服务系统本机执行；本次检测发现 SSH 22 端口拒绝连接。

## 在夹爪服务系统上执行

先在旧夹爪服务终端按 Ctrl+C，释放串口和 5005 端口。不要同时运行两个服务。
新版在启动时会激活夹爪。

可在新的目录独立部署，避免改动原项目。使用运行旧服务的 Python 环境
（已安装 pyserial），执行：

```bash
git clone --branch main https://github.com/KnightOrNot/xcore-gripper-2F85.git \
  "$HOME/xcore-gripper-follow"
cd "$HOME/xcore-gripper-follow"

# 确认 pyserial 可导入；若不可导入，先切换到原服务的 Python 环境
python3 -c 'import serial; print(serial.__version__)'
# 读取适配器列表；沿用旧服务实际使用的夹爪串口
python3 -m serial.tools.list_ports -v
```

确认新目录的 `git log -1 --oneline` 包含 `d250051` 或后续提交。
将以下 `/dev/ttyUSB0` 替换为刚确认的实际夹爪串口（推荐 by-id 路径），
直接从源码启动新版，避免调用 PATH 中残留的旧服务：

```bash
PYTHONPATH=src python3 -m xcore_gripper_2f85.gripper_server \
  --host 0.0.0.0 --port 5005 --serial-port /dev/ttyUSB0
```

保持该终端运行。若新部署目录已经存在，请在该目录检查 `git status`，
没有本地改动时使用 `git pull --ff-only` 更新，无需再次克隆。

## 在控制电脑上验证并跟随

先只读检查新版服务：

```bash
cd /home/knight/projects/xcore/xcore-controller
./xcore-sdk-python/.venv/bin/xcore-sdk-python gripper-check \
  --gripper-host 192.168.2.225
```

成功输出应有 `ok: true`、`streaming: true` 和实际 `position_raw`。
此检查不发送运动命令、不连接 CR7，也不打开 GELLO 串口。

再保持 GELLO 在期望姿态，启动统一跟随：

```bash
./start_gello_follow.sh --enable-motion
```

脚本默认使用 `.225:5005`、对齐 SDK 速度 `1000 mm/s`，
实时跟随速度独立由 `--max-speed-deg` 指定。确认后先对齐，随后从同一个
GELLO 读取进程发送六轴目标和独立夹爪目标。Ctrl+C 结束跟随。
