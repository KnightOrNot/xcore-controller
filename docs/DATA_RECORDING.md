# CR7 与独立 Robotiq 夹爪适配

原有 `lerobot-converter` 命令、`converter.py`、PiPER-X 数据契约及功能保持原样。
CR7 使用新增 `xcore-controller/tools/convert_cr7.py`，复用原有时间戳重采样、feature 构造和
LeRobot 数据集工厂，不修改原入口的格式校验或默认输出。

## 使用方法

在 `xcore-controller` 使用 `start_data_record.sh` 记录；或手动转换已保存的 raw session：

```bash
./lerobot-converter/.venv/bin/python tools/convert_cr7.py \
  data/raw/session_YYYYMMDD_HHMMSS data/lerobot/session_YYYYMMDD_HHMMSS \
  --repo-id local/cr7_gello_session_YYYYMMDD_HHMMSS --fps 30
```

也可以在 `xcore-controller` 目录使用 uv 执行：

```bash
uv run --project lerobot-converter --extra dataset python tools/convert_cr7.py \
  INPUT_SESSION OUTPUT_DATASET --fps 30
```

输出目录必须不存在，raw 输入不会被修改，数据不会上传至 Hugging Face。
原有 PiPER-X 转换继续使用原来的 `uv run --extra dataset lerobot-converter ...`。

## CR7 raw 格式

布局沿用 `manifest.json` 和 `episodes/episode_*.jsonl`。
manifest 使用 `format=xcore_cr7_gello_raw`、`robot_type=xmate_cr7`，版本为 1。
记录支持 R 开始、S 保存、D 丢弃；中断后留下的 `.jsonl.partial` 不参与转换。
记录入口的 Ctrl+C 先停止跟随和记录、关闭实时 SDK，会话释放后六轴回零，
再转换已保存片段；回零过程不写入训练数据。速度沿用 `--prepare-speed`。
可用 `--no-return-zero` 关闭回零；回零过程中再次 Ctrl+C 会请求停止回零。

每帧包含时间戳、连续 sequence，以及：

| 字段 | 含义 |
| --- | --- |
| `action` | 六轴请求目标（rad）和夹爪请求闭合度（0～1） |
| `joint_positions` | 六轴实际 SDK 反馈（rad）和夹爪实际闭合度（0～1） |
| `gripper_position` | 与 `joint_positions` 最后一项一致的实际闭合度 |
| `arm_feedback_time_ns` | 同机 SDK 服务成功读取反馈的单调时间 |
| `gripper_feedback_time_ns` | 客户端收到实际夹爪反馈的本机单调时间 |
| `gripper_position_raw` | 实际夹爪原始位置；由记录端保存 |

目标经过机械臂限速/插值和夹爪独立线程执行，因此 `action` 不等于实际反馈。
闭合度使用实际 raw 位置及夹爪开闭端点标定映射。

CR7 适配只输出七维 `observation.state` 和 `action`，不生成没有实际采集的速度或
末端位姿 feature。时间戳重采样可能复用已有反馈，不代表较低频率的夹爪传感器
产生了新的高频测量。

## 质量报告与测试

`quality_report.json` 保留原有采样质量指标，并在 CR7 适配中增加两路实际反馈
刷新频率和最大反馈年龄。无效维度、非有限值、sequence 断裂、时间戳异常会报错。

```bash
./lerobot-converter/.venv/bin/python -m pytest -q tests
(cd lerobot-converter && .venv/bin/python -m pytest -q tests/test_converter.py)
```

新增功能的测试位于独立 `tests/test_cr7_converter.py`。离线验证不代表真机采集验收。
