#!/usr/bin/env bash
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$root_dir" python -m xcore_controller.launcher pull "$@"
