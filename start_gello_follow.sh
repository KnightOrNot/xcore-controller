#!/usr/bin/env bash
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$root_dir/xcoresdk-python/scripts/start_gello_follow.sh" "$@"
