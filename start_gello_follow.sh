#!/usr/bin/env bash
set -Eeuo pipefail

# 六轴实时跟随速度上限，单位 °/s；默认采用现有软件上限 75。
# 有效范围：0 < V <= 75（软件上限）；加速度仍为 40 °/s²。
# 优先级：命令行 --max-speed-deg > 环境变量 > 此处默认值。
max_speed_deg="${XCORE_FOLLOW_MAX_SPEED_DEG:-75}"

# 启动对齐的 SDK 速度参数（mm/s），与实时跟随限速独立。
prepare_speed="${XCORE_PREPARE_SPEED:-4000}"
# 默认同时跟随夹爪；夹爪服务需先启动。仅六轴测试使用 --arm-only。
# Ctrl+C／故障退出默认由共享 SDK 入口停止跟随后六轴回零；--no-return-zero 可禁用。
gripper_host="${XCORE_GRIPPER_HOST:-192.168.2.225}"
export XCORE_GRIPPER_HOST="$gripper_host"

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$root_dir/xcore-sdk-python/scripts/start_gello_follow.sh" \
    --max-speed-deg "$max_speed_deg" --prepare-speed "$prepare_speed" "$@"
