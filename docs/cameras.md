# 远端双 D435i：运行与数据语义

相机功能与机械臂控制解耦：相机开发不要求移动 CR7，也不需要停止夹爪服务。

## 拓扑

```text
本地控制电脑                       远端 rokae@192.168.2.225
127.0.0.1:8086 ── SSH 隧道 ──> 127.0.0.1:8086  cam1 (349522071221)
127.0.0.1:8087 ── SSH 隧道 ──> 127.0.0.1:8087  cam2 (349522072318)
```

- 每台相机一个独立服务进程，显式绑定序列号与端口。
- 远端 HTTP 只监听 loopback，不在局域网公开无认证的控制端口。
- 一个远端实例只有一个 pipeline；多个浏览器共享最新帧缓存，
  不会为每个查看者重复打开设备。
- 关闭网页不会停止采集；必须显式 `stop`。

## 命令

```bash
./scripts/start_camera.sh --no-open     # 两台：连接、按需启动 API、采集，打印页面
./scripts/start_camera.sh status
./scripts/start_camera.sh info --profiles
./scripts/start_camera.sh snapshot      # 本地 captures/cam1、captures/cam2
./scripts/start_camera.sh stop          # 停止采集，API 保留 idle
./scripts/start_camera.sh disconnect    # 只关闭隧道，应先 stop
./scripts/stop_camera.sh                # 两台 API 与服务全部停止并清理隧道
```

单台使用 `--camera cam1` 或 `--camera cam2`。远端主机可用
`XCORE_CAMERA_SSH_TARGET=user@host` 或 `--ssh-target` 覆盖。端口、远端主机和
截图目录的默认值见相机项目的 `config/default.toml`，controller 的
`config/default.toml` 提供 SSH 目标和本地截图根目录。

## 页面的数据语义

- 网页预览的深度是伪彩 JPEG，只用于查看，不能用于测量或训练。
- 截图另存原始 Z16 无损 16 位 PNG，并保留 `depth_scale`、各流内参、外参、
  独立帧号、时间戳和 timestamp domain。
- 默认保留原生深度视角；没有显式对齐时，不能把 RGB 同像素与深度一一对应。
- 设备时间与主机 monotonic 时间不得混用。当前远程预览**不是**双机硬同步，
  也**不是**与机械臂同步采集。

## 部署与配置

- 远端目录：`~/project/camera-realsense-d435i/`，独立 `.venv`。
- 用户 unit：`camera-realsense-d435i@cam1.service`、`@cam2.service`，默认
  `disabled`；本地 preview/connect 按需 SSH 启动。
- 现场配置：`~/.config/camera-realsense-d435i/cam1.json`、`cam2.json`；
  安装脚本保留已有 JSON，不用仓库默认值覆盖。
- 修改 JSON 后先停对应采集，再重启对应 unit；不要重启整机或夹爪。

## 当前现场状态（2026-10-21）

- 两台均为 USB 2.1，挂在同一个 Genesys Logic Hub 下；已验证 640×480@15fps
  双机同时采集，四路 MJPEG 均收到有效 JPEG。
- cam1 固件 5.17.3.10，cam2 固件 5.15.1.55；当前没有为统一版本升级固件。
- 网页 HTTP 和图像流已自动验证；页面排版与按钮交互仍需人工验收。
- 双机硬同步、IMU、连续录像和接入机械臂数据记录尚未实现。
