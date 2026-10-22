# 更新记录

本文件记录 controller 及顶层入口的行为变化。子项目的详细变更见各自的
`CHANGELOG.md`。

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
