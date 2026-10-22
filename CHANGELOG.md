# 更新记录

本文件记录 controller 及顶层入口的行为变化。子项目的详细变更见各自的
`CHANGELOG.md`。

## 2026-10-22

- 新增 `[robot].return_mode`（`start`/`saved`/`zero`/`none`），默认 `start`：
  启动跟随或记录前记录当前从臂实际姿态，退出（Ctrl+C、SIGTERM、正常结束、故障）时
  自动返回该姿态。`--return-mode` 可覆盖，`none`/`--no-return` 禁用返回。
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
