# 远端部署

本地 `./scripts/setup.sh` 只准备控制电脑。本文件说明另一台 Linux 主机（下称“远端”，
现场为 `rokae@192.168.2.225`）要装什么、怎么装。

> 状态说明：本文按**当前远端实际部署**整理（2026-10-26 核对），步骤是本机手工执行过的
> 流程，**尚未在一台全新机器上完整复验**，也还没有一键脚本。远端没有 `git`／`uv`／`pip`，
> HTTPS 被自签证书拦截，因此依赖**在本地构建后同步**，不在远端联网安装。

## 远端跑什么

| 组件 | 由谁启动 | 说明 |
| --- | --- | --- |
| `xcore-controller remote-serve` | `xcore-controller-hardware.service` | 唯一拥有 CR7 SDK 会话的进程：RT 跟随、夹爪、录制编排、转换调度 |
| LeLab 数据服务 | `xcore-dataset.service` | 只读浏览 + 受控删除，`--root ~/project/xcore-data/lerobot` |
| 两台 D435i | `camera-realsense-d435i@cam1/@cam2.service` | 唯一相机 pipeline，预览与无损记录共用 |
| 夹爪服务 | `xcore-gripper-follow.service` | 唯一夹爪串口 owner，TCP 5005 |

全部是 **user unit**，安装后保持 `disabled`（不开机／登录自启），由本地脚本 SSH
按需 `systemctl --user start`。远端账户必须启用 `loginctl enable-linger`，否则 SSH
断开后进程会被回收。

## 目录布局

```text
~/project/
├── xcore-controller/          # 源码快照（不是 git clone）
│   ├── src/ config/ scripts/ tools/ deploy/
│   ├── xcore-sdk-python/      # SDK 源码 + Release/ 里的 .so
│   ├── xcore-adapters  -> ../xcore-adapters     # 软链
│   └── xcore-dataset   -> ../xcore-dataset      # 软链
├── xcore-adapters/            # 源码快照
├── xcore-dataset/             # 源码快照
├── camera-realsense-d435i/    # 源码快照 + 自己的 .venv
├── xcore-gripper-follow/      # 夹爪部署项目
├── xcore-runtime/             # 运行环境（约 2.6 GB）
│   ├── cpython-3.11.16-linux-x86_64-gnu/   # SDK 角色解释器
│   ├── cpython-3.12.14-linux-x86_64-gnu/   # 数据角色解释器
│   ├── vendor311/                          # SDK 依赖（PYTHONPATH）
│   ├── dataset-venv/                       # LeRobot / LeLab / torch
│   └── media/{bin,lib}/                    # FFmpeg 7 可执行文件与共享库
└── xcore-data/                # 业务数据（约 4.5 GB 起）
    ├── raw/ lerobot/ staging/ jobs/ logs/ reports/
```

`~/project/xcore-controller` 里的两个软链是必须的：转换任务以该目录为 cwd 运行，
而 adapters／dataset 在仓库结构里是同级目录。

## 部署步骤

### 1. 准备账户与网络

```bash
# 在远端
sudo loginctl enable-linger "$USER"
mkdir -p ~/project ~/project/xcore-data/{raw,lerobot,staging,jobs,logs,reports}
```

本地确认免密 SSH 可用，并且 `[remote].camera_ssh_target` 指向该账户：

```bash
ssh -o BatchMode=yes rokae@192.168.2.225 'echo ok'
```

### 2. 同步源码

从本地仓库根目录 rsync（**不要**同步 `.venv`、`data`、`logs`、`.git`）：

```bash
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' --exclude 'logs' \
  --exclude 'captures' --exclude '__pycache__' \
  ./xcore-controller/ rokae@192.168.2.225:~/project/xcore-controller/
```

适配器与数据集两个仓库同步到同级目录，再补软链：

```bash
rsync -a --exclude '.git' --exclude '.venv' ./xcore-adapters/ rokae@192.168.2.225:~/project/xcore-adapters/
rsync -a --exclude '.git' --exclude '.venv' ./xcore-dataset/  rokae@192.168.2.225:~/project/xcore-dataset/
ssh rokae@192.168.2.225 'cd ~/project/xcore-controller &&
  ln -sfn ../xcore-adapters xcore-adapters && ln -sfn ../xcore-dataset xcore-dataset'
```

相机与夹爪服务各自有部署文档，见
[camera-realsense-d435i](../camera-realsense-d435i/README.md)（`deploy/install_service.py`）
和 [夹爪服务部署](GRIPPER_SERVER_UPDATE.md)。

### 3. 构建运行环境（在本地构建，再同步）

远端没有 `uv`／`pip`，HTTPS 又被自签证书拦截，所以依赖环境在本地生成后整目录同步。
`xcore-runtime/` 由两部分组成：解释器（可用 `uv python install 3.11.16`、`3.12.14`
生成的独立 CPython 目录）和数据虚拟环境。

```bash
# 本地：按 xcore-dataset/uv.lock 生成 3.12 数据环境
uv sync --project xcore-dataset --python 3.12 --locked --no-dev
# 然后把它同步成远端的 dataset-venv，并修正本地包的 .pth 指向远端源码路径
rsync -a xcore-dataset/.venv/ rokae@192.168.2.225:~/project/xcore-runtime/dataset-venv/
```

必须核对的三件事：

1. `dataset-venv` 是 **CPython 3.12**，SDK 角色是 **3.11.16**；两者的 NumPy／二进制
   ABI 不能混用。转换子进程会清空 `PYTHONPATH`／`PYTHONHOME`，不要改成继承。
2. `media/lib` 里的 FFmpeg 7 共享库来自锁定的 PyAV 15.1.0；TorchCodec 需要按 SONAME
   建立别名，并把 `media/bin`、`media/lib` 放进数据服务的 `PATH`／`LD_LIBRARY_PATH`。
   系统自带的 FFmpeg 版本不满足要求，**不要替换系统库**。
3. SDK 角色的 `PYTHONPATH` 包含 `xcore-controller/src`、`xcore-sdk-python/src`、
   `xcore-adapters/src`、`xcore-dataset/src` 和 `xcore-runtime/vendor311`。

当前远端实测版本（换版本前先在远端跑一次 `pip list` 对照）：

| 包 | 版本 |
| --- | --- |
| Python（数据环境） | 3.12.14 |
| Python（SDK 角色） | 3.11.16 |
| lerobot | 0.6.0 |
| LeLab | 0.1.0（锁定上游 commit） |
| torch | 2.11.0+cpu |
| av | 15.1.0 |
| torchcodec | 0.11.1 |

### 4. 安装 systemd 用户 unit

`deploy/install_role_services.py` 只写 unit 文件，**不安装运行依赖、不启动硬件**，
已存在的 unit 默认拒绝覆盖：

```bash
cd ~/project/xcore-controller
python3 deploy/install_role_services.py --check-only        # 先看会写什么
python3 deploy/install_role_services.py --add-missing       # 只补缺失的
systemctl --user daemon-reload
```

需要装出的 5 个 unit：`xcore-controller-hardware`、`xcore-controller-readonly`、
`xcore-controller-simulate`、`xcore-dataset`、`xcore-gripper-follow`。
安装后保持 disabled。

### 5. 自检

在本地执行（不会上电、不激活夹爪、不运动）：

```bash
./scripts/start_remote_record.sh --check-only
```

应当依次通过：远端 hardware API、夹爪 API、本地 GELLO、双相机、LeLab。
任何一步失败都会在进入运动前退出。

## 更新已有部署

源码改动后重复第 2 步的 rsync，再重启对应 unit：

```bash
ssh rokae@192.168.2.225 'systemctl --user restart xcore-controller-hardware.service'
```

只改数据侧（`xcore-dataset`）时重启 `xcore-dataset.service` 即可；不要为了数据改动
重启相机或夹爪。改了运行环境（第 3 步）才需要重启全部。

## 已知坑

| 现象 | 原因／处理 |
| --- | --- |
| 转换报 TorchCodec 加载失败 | 少了 `media/` 的 FFmpeg 7 库或 `LD_LIBRARY_PATH`，见第 3 步 |
| 转换子进程导入 NumPy 报 ABI 错 | 继承了 SDK 角色的 `PYTHONPATH`；转换器已主动清空，别改回去 |
| 第 5 步数据服务 502 | 上次退出停掉了远端 `xcore-dataset`，但本地网关还活着；`setup-session` 会幂等重启远端 unit |
| `systemctl --user` 报 unit 不存在 | 账户不是部署时那个，或没有 `enable-linger` |
| 相机起不来 | 先看是否为该序列号的设备，再确认 `~/project/camera-realsense-d435i/.venv` 和 USB 带宽 |

## 尚未自动化

以下仍要手工完成，换新机器前请预留时间：

- 没有任何一键部署脚本；解释器和 `dataset-venv` 依赖本地构建后 rsync。
- 没有远端版本清单文件（`deps.lock`），当前版本靠本文表格和 `pip list` 对齐。
- 相机与夹爪的部署各自独立（见各自文档），没有统一入口。
