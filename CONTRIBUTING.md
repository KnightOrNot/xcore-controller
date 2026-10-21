# 贡献与开发检查

## 修改范围

- controller 自身只放脚本、文档、工具和测试；设备驱动、跟随算法和相机采集
  属于各自 submodule。不要跨 Git 边界搬动源码。
- 先分别检查父仓库和子模块的 `git status --short`。现场可能有未提交的用户改动，
  不要 `reset --hard`、清理现场配置或把无关变更混入提交。
- 子模块修改先在子仓库提交，再更新父仓库指针；发布时先推送子仓库，再推送父仓库。
- 不提交密码、SSH 私钥、现场标定、退出姿态、数据集、日志、相机画面和 `.venv`。

## 默认参数

- 新增可调参数时，先放入对应项目的 `config/default.toml`，命令行显式值优先。
- controller 脚本通过 `tools/config_defaults.py --get section.key` 或 `--shell` 读取；
  不要在脚本里再写一份默认值。
- 子模块的默认配置文件与 `src/<package>/default.toml` 保持一致（符号链接），
  避免安装后出现第二份配置。

## 离线检查

不启动硬件、不连接机械臂、不打开相机的情况下运行：

```bash
# controller
./lerobot-converter/.venv/bin/python -m pytest tests -q

# SDK
uv run --project xcore-sdk-python xcore check

# 各子项目
uv run --project xcore-sdk-python --with pytest --with ruff pytest -q
uv run --project xcore-gripper-2F85 --with pytest --with ruff pytest -q
uv run --project camera-realsense-d435i --with pytest --with ruff pytest -q
```

修改配置加载后，至少验证：

```bash
./scripts/setup.sh --check-only
python3 tools/config_defaults.py --json
uv run --project xcore-sdk-python xcore doctor
```

## 真机规则

- 默认裸命令不授权运动；只有显式 `--enable-motion` 且现场确认后才跟随。
- 启动对齐时主臂必须不动；旧会话完全退出前不能启动第二个会话。
- 不通过删除限位检查、自动截断或 ±2π 包装来绕过限位错误。
- 相机、夹爪和机械臂互不替代；不要为了相机改动重启夹爪或整机。
- 功能或部署状态变化后更新 `AGENTS.md`，写清“代码已实现”“离线测试通过”
  和“硬件已实测”的区别。
