#!/usr/bin/env bash
set -Eeuo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# 默认参数来自 config/default.toml；已存在的 XCORE_* 环境变量优先。
config_python="$root_dir/xcore-sdk-python/.venv/bin/python"
[[ -x "$config_python" ]] || config_python="$(command -v python3 || true)"
if [[ -f "$root_dir/config/default.toml" || -f "$root_dir/tools/config_defaults.py" ]]; then
    [[ -n "$config_python" ]] || { echo '缺少 Python 3.11+，无法读取 config/default.toml' >&2; exit 1; }
    config_arguments=("$root_dir/tools/config_defaults.py" --shell)
    [[ -z "${XCORE_CONFIG:-}" ]] || config_arguments+=(--config "$XCORE_CONFIG")
    config_shell="$("$config_python" "${config_arguments[@]}")" || {
        echo '读取 config/default.toml 失败' >&2; exit 1;
    }
    eval "$config_shell"
fi

# 六轴实时跟随速度上限，单位 °/s；默认采用现有软件上限 75。
# 有效范围：0 < V <= 75（软件上限）；加速度仍为 40 °/s²。
# 优先级：命令行 --max-speed-deg > 环境变量 > config/default.toml。
max_speed_deg="${XCORE_FOLLOW_MAX_SPEED_DEG:-75}"

# 启动对齐的 SDK 速度参数（mm/s），与实时跟随限速独立。
prepare_speed="${XCORE_PREPARE_SPEED:-4000}"
# 默认同时跟随夹爪；夹爪服务需先启动。仅六轴测试使用 --arm-only。
# Ctrl+C／故障退出默认返回 SDK config/exit_pose.json 保存的姿态；--no-return 可禁用。
gripper_host="${XCORE_GRIPPER_HOST:-192.168.2.225}"
export XCORE_GRIPPER_HOST="$gripper_host"

exec bash "$root_dir/xcore-sdk-python/scripts/start_gello_follow.sh" \
    --max-speed-deg "$max_speed_deg" --prepare-speed "$prepare_speed" \
    --gripper-port "${XCORE_GRIPPER_PORT:-5005}" "$@"
