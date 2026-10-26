# 更新记录

本文件记录 controller 及顶层入口的行为变化。子项目的详细变更见各自的
`CHANGELOG.md`。

## 2026-10-26

- 修正 S 保存时无即时反馈和忙时按键积压：显示保存／完成提示，保持单键终端模式，
  忽略积压 S/D，保留一次 R 或优先 Q；退出恢复终端设置。增加真实伪终端交互回归。
- `start_remote_record.sh` 默认一键准备控制器、夹爪、GELLO、双 RGBD、LeLab 和 SSH
  连接，复用已有服务，一次确认后按需激活夹爪并进入跟随；新增 `--check-only`／
  `--no-auto-start`、就绪校验、单实例锁及自建后台进程清理。现场无运动冷启动通过。
- 修复夹爪初始反馈在 RT 启动期间过期导致整机停止：启动前持续只读轮询，arm 等待
  RT 回调推进和新鲜反馈后才成功，启动异常直接返回给终端。
- SDK 去除额外零距离 RT MoveJ 初始化，最终回调结束后显式 stopLoop／stopMove；
  同会话两轮 RT 实机启停通过。清理未完成时拒绝后续运动，避免叠加会话。
- 新增 watch-motion 和脚本健康监测，远端异常不再静默；故障退出先 stop、不自动返回。
  转换子进程隔离 3.11 PYTHONPATH／PYTHONHOME，空会话不提交转换。
- 修复 S 保存期间 `/leader` 应答间接等待 recorder 状态锁的问题；主臂接收只做
  快速确认，录制生命周期锁与状态锁分离，保存不再持状态锁等待记录线程退出。
- 新远端数采链路接入已有 TCP 夹爪连续跟随：显式 arm 前只读检查激活状态，
  arm 后映射 ID7，独立线程下发；state/action 记录实测／期望开合，停臂时停止夹爪。
  `[robot].follow_gripper=true` 默认开启，入口增加夹爪就绪预检和未激活提示。
- 修复远端 prepare／Q 返回的模式设置顺序：先选择 NRT，再切自动和上电，
  `movej` 不重复切模式；失败清理不恢复上电，脚本退出返回失败时保留非零退出码。
  离线回归通过，真机返回待现场验证。
- 修复 dataset 子模块 Python 3.11 raw writer 与 Python 3.12 LeRobot／LeLab
  extras 的依赖条件，使 uv 可生成跨版本锁文件。

## 2026-10-22

- 新增远端运动角色：`remote-serve --hardware`、显式 `arm/prepare/stop/exit/pose`、
  远端主臂映射（解缠／标定／2π 分支）与 vendor FK pose10；断流锁定、重连不自动 arm。
  真实运动尚未现场验收；`xcore-controller-hardware.service` 安装项已加入部署脚本但未安装。
- 新增远端 raw 会话：`session/start|stop`、`episode/start|save|discard`，
  双相机无损帧＋EE10 样本按远端 host 时间对齐，失败片段拒绝提交；
  xcore-dataset 放宽到 Python 3.11 以便远端 SDK 运行时导入 raw 写入器。
- xcore-dataset 支持 session→多 LeRobot episode 转换，并新增持久转换队列
  （queued/running/ready/failed、崩溃重排、失败重试、staging 保留）；
  controller 在 `session/stop` 后自动排队转换，不在 3.11 SDK 环境加载 LeRobot。
- 新增 `start_remote_record.sh`、`start_data_record.sh --remote` 和
  `convert_dataset.sh`；部署脚本支持添加缺失的 hardware unit；
  xcore-adapters 新增只读附着客户端。
- 修复长时运动命令被 2 秒 HTTP 超时误判为失败的问题：按动作设置超时，
  `prepare`／`exit` 等可等待数分钟；超时提示先检查远端状态。
- 修复 arm 后约 1 秒误判断流：远端 HTTP 桥的 `remote_stale_timeout_s` 默认改为 3 秒，
  降低 GIL 饥饿、放宽 bridge 超时，并在状态中暴露 `leader_age_s`。
- hardware 模式的 `LeaderInbox` 超时与运动看门狗统一为
  `remote_stale_timeout_s`，修复 0.5 秒 inbox 超时导致的 arm 后误停。
- 退出返回修复：CLI 显示 HTTP 错误体，服务端记录失败命令；返回前等待 RT 收尾到
  idle，避免 `movej` 在非 idle 状态被 409 拒绝。
- 新增本地网页数采面板（`start_remote_record.sh --web`、`xcore-controller web`）：
  单后台任务、一次性运动确认令牌、只读模式、状态与双 RGBD 预览、LeLab 入口。
- 新增 pose10／joints 两种数据表示：joints 从 raw 关节字段构建七维 state/action，
  发布 `representation.json`；`pull_dataset.sh --pose|--joints|--list` 校验表示后拉取。
- 重做网页面板布局：全高自适应、2×2 预览、单画面/整页全屏、预览最大化、
  状态指标卡、MJPEG 只在 URL 变化时重连并在断流后重试。
- 修复真实会话转换：同一相机帧被多个样本引用时不再误报元数据冲突；记录时帧龄
  与时钟误差分离并写入质量报告；转换容差默认 100ms。刚保存的 real session
  已重新转换并在 LeLab 可见。
- LeLab 删除按钮修复：新增受控的已发布 revision 删除接口（仅 READY 目录、本地磁盘，
  拒绝路径穿越／symlink／raw／Hub），删除三个测试版本；网页面板修正主臂帧龄显示
  并补齐丢弃按钮测试。
- 相机子模块升级到 `76d33ac`：同一采集 pipeline 新增无损 RGB／Z16 连续记录，
  有界队列／写盘线程／`COMPLETE.json` 提交标记；真实双机 10 秒各 150 帧零丢帧。
- 新增 `[robot].return_mode`（`start`/`zero`/`none`），默认 `zero`：
  退出时返回六轴 0°；`start` 在启动前记录当前从臂实际姿态并返回该姿态，
  `none` 禁用返回。`--return-mode` 可覆盖。
- 同步更新 README、配置/CLI 文档和 AGENTS；未改变现场固定姿态文件。

## 2026-10-21

- 配置审查修复：连续截图使用独立时间戳目录；夹爪端口传递到跟随入口；校验非法端口、类型及非有限数值，工具支持 XCORE_CONFIG。

- 新增 `config/default.toml`，集中管理 CR7 地址、GELLO 串口、远端主机、
  跟随限速、记录路径和超时；脚本通过 `tools/config_defaults.py` 读取。
- 新增 `docs/`：架构、安装、相机、CLI、配置、故障排查和子模块配置。
- 新增 `CONTRIBUTING.md`、`THIRD_PARTY_NOTICES.md` 和本文件。
- 相机项目接入为第五个 submodule；`scripts/start_camera.sh`、`scripts/stop_camera.sh`
  支持双 D435i 的按需启动、状态、截图和停止。
- 所有 controller shell 入口迁移到 `scripts/`，根目录不再保留旧入口。
- 退出行为从六轴回零改为返回实测保存姿态；`return-pose` 为规范命令，
  `return-zero` 保留为兼容别名。

## 2026-10-08

- 建立控制与转换环境；完成 CR7 跟随、夹爪跟随、现场标定和 raw 记录。
- 数据转换拆分为独立的 Python 3.12 环境。

## 2026-09

- 初始工程：GELLO 六轴映射到 ROKAE xMate CR7 与 Robotiq 2F-85。
