#!/usr/bin/env bash
# Queue or retry remote conversion for a sealed session; never starts hardware.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$("$root_dir/tools/config_defaults.py" --shell)"

usage() {
    cat <<'EOF'
用法:
  scripts/convert_dataset.sh SESSION_ID            # 排队并执行该会话的转换
  scripts/convert_dataset.sh --retry JOB_ID        # 重试失败的转换任务
  scripts/convert_dataset.sh --list                # 查看任务队列

会话必须是远端 ~/project/xcore-data/raw/ 下已封存的 session。
转换在远端独立 Python 3.12 数据环境运行，不连接机械臂或相机。
EOF
}

mode=queue
value=""
case "${1:-}" in
    --retry) mode=retry; value="${2:?缺少 job id}" ;;
    --list) mode=list ;;
    ""|-h|--help) usage; exit 0 ;;
    *) value="$1" ;;
esac
if [[ -n "$value" && ! "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "非法 ID：$value" >&2
    exit 2
fi

target="${XCORE_CAMERA_SSH_TARGET:-rokae@192.168.2.225}"
remote_home='$HOME'
python="$remote_home/$XCORE_REMOTE_DATASET_PYTHON"
data_root="$remote_home/$XCORE_REMOTE_DATA_ROOT"
dataset_project="$remote_home/project/xcore-dataset"
runtime="$remote_home/project/xcore-runtime"

case "$mode" in
    list) command="jobs --root $data_root" ;;
    retry) command="jobs --root $data_root --retry $value --run" ;;
    queue) command="queue $data_root/raw/$value --root $data_root --dataset-id $value && \
$python -m xcore_dataset.cli jobs --root $data_root --run" ;;
esac

ssh -T -o BatchMode=yes -o ConnectTimeout=5 "$target" \
    "cd $dataset_project && \
     export PATH=$runtime/media/bin:/usr/bin:/bin && \
     export LD_LIBRARY_PATH=$runtime/media/lib:$runtime/dataset-venv/lib/python3.12/site-packages/torch/lib && \
     $python -m xcore_dataset.cli $command"
