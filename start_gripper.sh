#!/usr/bin/env bash
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$root_dir/xcore-gripper-2F85/run_gripper.sh" "$@"
