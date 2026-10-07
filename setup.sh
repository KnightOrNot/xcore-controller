#!/usr/bin/env bash
# Initialize independent subprojects and their Python environments.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
check_only=false
skip_submodules=false

usage() {
    cat <<'EOF'
用法：./setup.sh [--check-only] [--skip-submodules]
初始化三个子模块并配置独立 Python 环境。需要已安装 git、pyenv、uv 和 Python 3.11。
--check-only       只检查现有环境与命令，不安装、不连接硬件
--skip-submodules 保留当前子模块版本，只同步软件环境
EOF
}
while (( $# )); do
    case "$1" in
        --check-only) check_only=true ;;
        --skip-submodules) skip_submodules=true ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
for task_command in git pyenv uv; do
    command -v "$task_command" >/dev/null || { echo "缺少命令：$task_command" >&2; exit 1; }
done
if [[ "$check_only" == false && "$skip_submodules" == false ]]; then
    git -C "$root_dir" submodule sync
    git -C "$root_dir" submodule update --init
fi
for project in xcore-sdk-python xcore-gello-software xcore-gripper-2F85; do
    project_dir="$root_dir/$project"
    [[ -f "$project_dir/.python-version" ]] || { echo "子模块尚未初始化：$project" >&2; exit 1; }
    requested="$(tr -d '\r\n' < "$project_dir/.python-version")"
    resolved="$(pyenv latest -k "$requested")"
    python_path="$(PYENV_VERSION="$resolved" pyenv which python)"
    echo "$project：Python $resolved"
    if [[ "$check_only" == false ]]; then
        if [[ "$project" == xcore-gello-software ]]; then
            [[ -x "$project_dir/.venv/bin/python" ]] || uv venv --python "$python_path" "$project_dir/.venv"
            uv pip install --python "$project_dir/.venv/bin/python" \
                -r "$project_dir/requirements.txt" dynamixel-sdk -e "$project_dir"
        else
            UV_NO_MANAGED_PYTHON=1 uv sync --project "$project_dir" \
                --frozen --inexact --python "$python_path"
        fi
    fi
done
"$root_dir/xcore-sdk-python/.venv/bin/xcore-sdk-python" --help >/dev/null
"$root_dir/xcore-gello-software/.venv/bin/xcore-gello-software" --help >/dev/null
"$root_dir/xcore-gello-software/.venv/bin/xcore-gello-software" launch-nodes --help >/dev/null
"$root_dir/xcore-gripper-2F85/.venv/bin/xcore-gripper-2f85" --help >/dev/null
"$root_dir/xcore-gripper-2F85/.venv/bin/xcore-gripper-2f85-server" --help >/dev/null
echo "三个子项目的环境与命令入口检查通过。"
