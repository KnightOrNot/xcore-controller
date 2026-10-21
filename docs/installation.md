# 安装与环境

## 要求

- 控制电脑：Ubuntu Linux，Python 3.11（控制）与 3.12（数据转换），
  Git、pyenv、uv、iproute2、SSH 客户端、`flock`。
- CR7 控制器与控制电脑在同一有线网段；控制电脑通常为 `192.168.2.100/24`。
- GELLO 主臂通过 USB-FTDI 串口连接本地电脑，用户属于 `dialout` 组。
- 夹爪和两台 D435i 连接 Linux 服务机（现场 `rokae@192.168.2.225`）。

## 一键初始化

```bash
git clone git@github.com:KnightOrNot/xcore-controller.git
cd xcore-controller
./scripts/setup.sh
```

setup 会初始化五个 submodule，按各自的 `.python-version` 创建独立环境：

| 子项目 | Python | 说明 |
| --- | --- | --- |
| xcore-sdk-python | 3.11 | CR7 SDK 扩展要求 CPython 3.11 |
| xcore-gello-software | 3.11 | GELLO 上游依赖 |
| xcore-gripper-2F85 | 3.11 | 夹爪 TCP 服务 |
| camera-realsense-d435i | 3.11 | 本地客户端只用标准库 |
| lerobot-converter | 3.12 | LeRobot 与数据集依赖 |

常用参数：

```bash
./scripts/setup.sh --check-only       # 只检查，不安装、不连接硬件
./scripts/setup.sh --skip-submodules  # 保留本地子模块改动
```

## 手动同步

已有 pyenv 和 uv 时，可分别执行：

```bash
git submodule update --init
uv sync --project xcore-sdk-python --frozen --python 3.11
uv sync --project xcore-gripper-2F85 --frozen --python 3.11
uv sync --project camera-realsense-d435i --frozen --python 3.11
uv sync --project lerobot-converter --frozen --extra dataset --python 3.12
```

GELLO 使用 setuptools 和 `requirements.txt`；`scripts/setup.sh` 会安装
`dynamixel-sdk` 并以 editable 方式安装该仓库。

## 有线网络

控制电脑的有线地址应使用 `192.168.2.0/24`，且不要为有线网卡配置默认网关；
外网由 WiFi 提供。可用 SDK 的只读网络检查：

```bash
uv run --project xcore-sdk-python xcore network check
uv run --project xcore-sdk-python xcore network configure --interface <网卡>
```

修改地址属于系统配置，不会运动机械臂。

## 串口与标定

```bash
sudo usermod -aG dialout "$USER"
ls -l /dev/serial/by-id/
```

GELLO 的稳定路径写入 `config/default.toml` 的 `[gello].port`。首次使用必须
建立现场标定：

```bash
uv run --project xcore-sdk-python xcore follow-check
uv run --project xcore-sdk-python xcore follow-calibrate --ref-current
```

`config/cr7_calib.json` 和 `config/exit_pose.json` 是现场文件，默认被 Git 忽略。
新 clone 不能凭空运行真机跟随；退出返回姿态也必须由现场重新采集或提供。

## 验证

```bash
./scripts/setup.sh --check-only
uv run --project xcore-sdk-python xcore doctor
uv run --project xcore-sdk-python xcore status --timeout 5   # 只读，连接 CR7
```

`doctor` 不连接硬件；`status` 只读反馈。确认网络、供电和急停状态后，再按
[README](../README.md) 做只读预览和真实跟随。

## 远端服务

夹爪与相机的部署目录、用户 unit 和 SSH 访问见各子项目文档。远端服务默认
`disabled`（不开机/登录自启），由本地脚本按需 SSH 启动。不要为相机变更
重启夹爪或整机。
