# 子模块默认配置

五个一级 submodule 各自提供 `config/default.toml`。controller 配置不会隐式
注入子模块；跨项目参数由 controller 以显式 CLI/环境变量传入。每个包的
`src/<package>/default.toml`（GELLO 为 `<package>/default.toml`）是指向仓库配置的
符号链接，保证 editable 安装和构建后都能找到同一份默认值。

| 子模块 | 配置范围 | 覆盖方式 |
| --- | --- | --- |
| xcore-sdk-python | robot、monitor、motion、server、gello、calibration、prepare、return、gripper、follow、recording、network | `xcore ... --config PATH` |
| xcore-gello-software | 只读 `read` 的串口、频率、采样数和夹爪端点 | `XCORE_GELLO_CONFIG=PATH` |
| xcore-gripper-2F85 | 服务端监听、客户端连接、运动默认值和 watch 周期 | `xcore-gripper-2f85 --config PATH`；服务端 `--config PATH` |
| lerobot-converter | repo_id、FPS、速度/末端位姿特征 | `lerobot-converter ... --config PATH` |
| camera-realsense-d435i | 本地相机选择、SSH 目标、端口、截图目录、serve 主机/端口 | `--defaults PATH`；serve 的 `--config` 仍是现场 JSON |

显式命令行参数优先。环境变量在 SDK 和夹爪客户端中继续有效
（`XCORE_ROBOT_IP`、`XCORE_LOCAL_IP`、`GRIPPER_HOST`、`GRIPPER_PORT`、
`XCORE_CAMERA_SSH_TARGET`、`XCORE_GELLO_CONFIG`）。

## 现场文件与默认值的边界

以下内容**不**写入各仓库的 `default.toml`，仍使用 Git 忽略的现场文件：

- CR7 单姿态标定：`xcore-sdk-python/config/cr7_calib.json`。
- 退出返回姿态：`xcore-sdk-python/config/exit_pose.json`。
- 每台相机的 profile 与序列号：远端
  `~/.config/camera-realsense-d435i/cam1.json`、`cam2.json`。
- 数据集、raw 记录、日志和截图。

默认值只描述设备和流程的可复现参数（地址、端口、串口、限速、路径），
不代替现场标定。

## SDK 配置分组

| 表 | 主要内容 |
| --- | --- |
| `[robot]` | CR7 地址、本机地址、总超时、厂商扩展目录 |
| `[monitor]` | 只读采样时长与间隔 |
| `[motion]` | `movej`/`move-joint` 的 SDK 速度、步长、到位容差 |
| `[server]` | 跟随服务 host/port、状态频率、六轴限速、加速度、看门狗、门限 |
| `[gello]` | 主臂串口、波特率、六轴方向 |
| `[calibration]` | 标定文件、采样数、间隔 |
| `[prepare]` | 启动对齐速度、步长、容差、超时和夹爪端点 |
| `[return]` | 退出姿态文件、速度、步长、容差、超时 |
| `[gripper]` | TCP 端口、ID、角度端点、原始位置、频率、速度、力、超时 |
| `[follow]` | 客户端 host/port、控制频率、对齐门限 |
| `[recording]` | 任务描述、队列容量、反馈最大年龄 |
| `[network]` | 有线网卡和临时 IPv4 地址 |

详细字段和校验见 [SDK 配置](../../xcore-sdk-python/docs/reference/config.md)。
