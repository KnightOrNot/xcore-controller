#!/usr/bin/env bash
# Remote data collection: local GELLO + bridge + remote SDK/cameras.
# Motion is opt-in; episode recording additionally requires an armed follow.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

task=""
enable_motion=false
prepare=true
while (($#)); do
    case "$1" in
        --task) task="${2:?missing task}"; shift 2 ;;
        --enable-motion) enable_motion=true; shift ;;
        --no-prepare) prepare=false; shift ;;
        -h|--help)
            cat <<'EOF'
用法: scripts/start_remote_record.sh --task "任务" --enable-motion [--no-prepare]

要求先运行：
  ./scripts/start_gello_service.sh
  ./scripts/start_remote_controller.sh --hardware
本脚本会自动启动本地数据桥。

按键：R 开始 episode，S 保存，D 丢弃，P 状态，Q 退出。
--enable-motion 会先做对齐（prepare）再 arm，两者都是真实运动；
不执行该参数时只能查看状态，不能开始记录。
退出时按 config/default.toml 的 return_mode 返回（none 则不返回）。
EOF
            exit 0
            ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

eval "$("$root_dir/tools/config_defaults.py" --shell)"
[[ -n "$task" ]] || task="$XCORE_TASK"
controller_url="http://127.0.0.1:$XCORE_CONTROLLER_SERVICE_PORT"
leader_url="http://127.0.0.1:$XCORE_GELLO_SERVICE_PORT"

run() { uv run --project "$root_dir" xcore-controller "$@"; }
remote_call() { run command "$controller_url" "$@"; }
json() { python3 -m json.tool; }

if ! run status "$controller_url" >/dev/null 2>&1; then
    echo "远端 controller 不可达：$controller_url" >&2
    echo "请先运行 ./scripts/start_remote_controller.sh --hardware" >&2
    exit 1
fi
if ! curl -fsS --max-time 2 "$leader_url/sample" >/dev/null; then
    echo "本地 GELLO 服务不可达：$leader_url" >&2
    echo "请先运行 ./scripts/start_gello_service.sh" >&2
    exit 1
fi

if [[ "$enable_motion" != true ]]; then
    echo "未授权运动：可以查看状态，但不能开始 episode。"
    echo "需要现场确认安全后加 --enable-motion 重新运行。"
fi

bridge_pid=""
episode_active=false
session_started=false
armed=false
cleanup() {
    set +e
    if [[ "$episode_active" == true ]]; then
        echo "退出：当前 episode 未保存，按丢弃处理。"
        remote_call episode/discard --reason "script exit" >/dev/null
    fi
    if [[ "$armed" == true ]]; then
        echo "退出返回（模式 $XCORE_RETURN_MODE）：真实运动。"
        remote_call exit --return-mode "$XCORE_RETURN_MODE" >/dev/null
    fi
    if [[ "$session_started" == true ]]; then
        remote_call session/stop >/dev/null
    fi
    if [[ -n "$bridge_pid" ]]; then
        kill "$bridge_pid" 2>/dev/null
        wait "$bridge_pid" 2>/dev/null
    fi
}
trap cleanup EXIT

if [[ -x "$root_dir/.venv/bin/xcore-controller" ]]; then
    "$root_dir/.venv/bin/xcore-controller" bridge \
        --leader-url "$leader_url" --remote-url "$controller_url" &
else
    run bridge --leader-url "$leader_url" --remote-url "$controller_url" &
fi
bridge_pid=$!
sleep 1

if [[ "$enable_motion" == true ]]; then
    echo "即将执行对齐（prepare）并进入实时跟随。"
    echo "请保持 GELLO 静止，确认 CR7 周围安全。"
    read -r -p "输入 y 继续: " answer
    if [[ "$answer" != y && "$answer" != Y ]]; then
        echo "已取消（未运动）。"
        exit 1
    fi
    if [[ "$prepare" == true ]]; then
        echo "正在对齐（prepare），可能需要数分钟；此终端会等待，请勿关闭。"
        remote_call prepare | json
    fi
    echo "对齐完成，正在 arm（进入实时跟随）。"
    remote_call arm | json
    armed=true
fi

remote_call session/start --task "$task" | json >/dev/null
session_started=true
echo "会话已创建，任务：$task"

while true; do
    read -r -n1 -s key || break
    echo
    case "${key,,}" in
        r)
            if [[ "$armed" != true ]]; then
                echo "未 armed，不能开始记录。" >&2
                continue
            fi
            if [[ "$episode_active" == true ]]; then
                echo "已有活动 episode。" >&2
                continue
            fi
            if remote_call episode/start >/dev/null; then
                episode_active=true
                echo "开始记录。"
            else
                echo "开始记录失败。" >&2
            fi
            ;;
        s)
            [[ "$episode_active" == true ]] || { echo "没有活动 episode。" >&2; continue; }
            episode_active=false
            remote_call episode/save | json
            ;;
        d)
            [[ "$episode_active" == true ]] || { echo "没有活动 episode。" >&2; continue; }
            episode_active=false
            remote_call episode/discard --reason "operator discard" | json
            ;;
        p) remote_call pose | json ;;
        h|'?')
            echo "R 开始，S 保存，D 丢弃，P 位姿，Q 退出"
            ;;
        q) break ;;
        *) ;;
    esac
done
