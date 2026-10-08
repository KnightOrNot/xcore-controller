#!/usr/bin/env bash
# Record through the existing single-reader follow launcher, then convert offline.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
raw_root="$root_dir/data/raw"
dataset_root="$root_dir/data/lerobot"
dataset_fps=30
convert=true
task="CR7 GELLO teleoperation"
gripper_host="${XCORE_GRIPPER_HOST:-192.168.2.225}"
follow_options=()
follow_pid=""
session_file=""
interrupted=false
stop_requested=false

usage() {
    cat <<'EOF'
用法：./start_data_record.sh [选项]
启动 CR7 六轴与外接夹爪跟随，并记录从臂实际反馈。启动前需运行夹爪服务。
R=开始，S=保存，D=丢弃，P=状态，H=帮助；Ctrl+C 停止跟随、六轴回零后转换已保存 episode。
未保存的 episode 保留为 .jsonl.partial，不自动转换。
  --raw-data-root PATH       默认 data/raw
  --lerobot-data-root PATH   默认 data/lerobot
  --dataset-fps N            默认 30
  --skip-conversion          仅记录 raw
  --task TEXT                任务描述
  --gripper-host HOST        默认 192.168.2.225，可用 XCORE_GRIPPER_HOST 覆盖
  --start-recording          对齐后立即开始 episode 0
  --show-state               循环打印状态；默认关闭，记录与故障检查不受影响
  --no-return-zero           禁用 Ctrl+C 退出后的六轴回零
其余 --ip、--local-ip、--gello-port、--calib、--hz、--prepare-*、--skip-prepare、
--calibrate-zero、--gripper-*、--record-*、--yes
参数传给统一跟随入口；无需另外运行 start_gello_follow.sh。
EOF
}

on_signal() {
    interrupted=true
    if [[ -n "$follow_pid" ]]; then
        # Bash background jobs inherit ignored SIGINT. USR1 requests the same
        # Ctrl+C shutdown in the follow launcher, including its return to zero.
        if [[ "$1" == INT ]]; then
            kill -USR1 "$follow_pid" 2>/dev/null || true
        elif [[ "$stop_requested" == false ]]; then
            kill -TERM -- "-$follow_pid" 2>/dev/null || true
        fi
        stop_requested=true
    fi
}
cleanup() {
    local result=$?
    trap - EXIT INT TERM
    if [[ -n "$follow_pid" ]] && kill -0 "$follow_pid" 2>/dev/null; then
        kill -TERM -- "-$follow_pid" 2>/dev/null || true
        wait "$follow_pid" 2>/dev/null || true
    fi
    [[ -z "$session_file" ]] || rm -f -- "$session_file"
    exit "$result"
}
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap cleanup EXIT

while (( $# )); do
    case "$1" in
        --raw-data-root) raw_root="${2:?缺少路径}"; shift 2 ;;
        --lerobot-data-root) dataset_root="${2:?缺少路径}"; shift 2 ;;
        --dataset-fps) dataset_fps="${2:?缺少 FPS}"; shift 2 ;;
        --skip-conversion) convert=false; shift ;;
        --task) task="${2:?缺少任务}"; shift 2 ;;
        --gripper-host) gripper_host="${2:?缺少夹爪地址}"; shift 2 ;;
        --start-recording|--yes|--skip-prepare|--calibrate-zero|--show-state|--no-return-zero) follow_options+=("$1"); shift ;;
        --ip|--local-ip|--gello-port|--calib|--port|--hz|--max-speed-deg|--prepare-speed|--prepare-motion-timeout|--prepare-max-step-deg|--record-queue-size|--record-feedback-max-age|--gripper-port|--gripper-id|--gripper-open-deg|--gripper-close-deg|--gripper-open-pos|--gripper-closed-pos|--gripper-hz|--gripper-speed|--gripper-force|--gripper-timeout|--gripper-stale-timeout)
            [[ $# -ge 2 ]] || { echo "$1 缺少参数" >&2; exit 2; }
            follow_options+=("$1" "$2"); shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
    esac
done
[[ "$dataset_fps" =~ ^[1-9][0-9]*$ ]] || { echo "FPS 必须为正整数" >&2; exit 2; }
converter_python="$root_dir/lerobot-converter/.venv/bin/python"
if [[ "$convert" == true ]]; then
    [[ -x "$converter_python" ]] || { echo "请先执行 ./setup.sh 安装转换器" >&2; exit 1; }
    "$converter_python" -c \
        'from lerobot.datasets.lerobot_dataset import LeRobotDataset'
fi
mkdir -p -- "$raw_root"
raw_root="$(cd -- "$raw_root" && pwd)"
session_file="$(mktemp /tmp/xcore-raw-session.XXXXXX)"
setsid bash "$root_dir/start_gello_follow.sh" --enable-motion \
    --gripper-host "$gripper_host" --raw-data-root "$raw_root" --task "$task" \
    --session-path-file "$session_file" "${follow_options[@]}" <&0 &
follow_pid=$!
set +e
while true; do
    wait "$follow_pid"
    follow_result=$?
    kill -0 "$follow_pid" 2>/dev/null || break
done
set -e
follow_pid=""

# The follow launcher has closed both the RT session and the return-zero session.
# Conversion must wait for that shutdown, including the Ctrl+C path.
if [[ -s "$session_file" ]]; then
    raw_session="$(<"$session_file")"
    if [[ "$convert" == true ]]; then
        shopt -s nullglob
        episodes=("$raw_session"/episodes/episode_*.jsonl)
        if (( ${#episodes[@]} )); then
            mkdir -p -- "$dataset_root"
            name="$(basename -- "$raw_session")"
            "$converter_python" "$root_dir/tools/convert_cr7.py" "$raw_session" "$dataset_root/$name" \
                --repo-id "local/cr7_gello_$name" --fps "$dataset_fps"
            echo "LeRobot 数据集：$dataset_root/$name"
        else
            echo "没有已保存 episode，跳过转换；未保存数据保留为 .partial。"
        fi
    fi
    echo "Raw session：$raw_session"
fi
if [[ "$interrupted" == true ]]; then
    if (( follow_result != 0 && follow_result != 130 && follow_result != 143 )); then
        exit "$follow_result"
    fi
    exit 130
fi
exit "$follow_result"
