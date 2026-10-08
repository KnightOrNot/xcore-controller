#!/usr/bin/env bash
set -Eeuo pipefail

# 六轴实时跟随速度上限，单位 °/s；修改下面的 3 即可调整默认值。
# 有效范围：0 < V <= 75（软件上限）；加速度仍为 40 °/s²。
# 优先级：命令行 --max-speed-deg > 环境变量 > 此处默认值。
max_speed_deg="${XCORE_FOLLOW_MAX_SPEED_DEG:-3}"

# 启动对齐的 SDK 速度参数（mm/s），与实时跟随限速独立。
prepare_speed="${XCORE_PREPARE_SPEED:-1000}"
# 默认同时跟随夹爪；夹爪服务需先启动。仅六轴测试使用 --arm-only。
gripper_host="${XCORE_GRIPPER_HOST:-127.0.0.1}"
export XCORE_GRIPPER_HOST="$gripper_host"

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$root_dir/xcore-sdk-python/scripts/start_gello_follow.sh" \
    --max-speed-deg "$max_speed_deg" --prepare-speed "$prepare_speed" "$@"
