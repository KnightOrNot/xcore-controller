#!/usr/bin/env bash
# Remote data collection: local GELLO + bridge + remote SDK/cameras.
# Motion is opt-in; episode recording additionally requires an armed follow.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

task=""
enable_motion=false
prepare=true
auto_start=true
check_only=false
web=false
web_port=""
while (($#)); do
    case "$1" in
        --task) task="${2:?missing task}"; shift 2 ;;
        --enable-motion) enable_motion=true; shift ;;
        --no-prepare) prepare=false; shift ;;
        --no-auto-start) auto_start=false; shift ;;
        --check-only) check_only=true; shift ;;
        --web) web=true; shift ;;
        --web-port) web_port="${2:?missing port}"; shift 2 ;;
        -h|--help)
            cat <<'EOF'
用法: scripts/start_remote_record.sh --task "任务" --enable-motion [--no-prepare]
      scripts/start_remote_record.sh --task "任务" --web [--enable-motion] [--web-port N]

默认按需启动本地 GELLO、远端 hardware API、夹爪、双 RGBD、LeLab 及 SSH 隧道。
首次安装 SDK／远端部署／SSH 密钥及现场标定须已完成。
--check-only     只启动并检查服务，不激活夹爪、不对齐、不 arm
--no-auto-start  使用已手动启动的服务，不自动启动整套环境
--web            启动本地数采网页，不进入终端 R/S/D 流程
--web-port N     覆盖 config/default.toml 的 [web].port

按键：R 开始 episode，S 保存，D 丢弃，P 状态，Q 退出。
--enable-motion 经一次现场确认后，必要时激活夹爪，再对齐（prepare）和 arm；
不执行该参数时只能查看状态，不能开始记录。
退出时按 config/default.toml 的 return_mode 返回（none 则不返回）。
EOF
            exit 0
            ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

command -v uv >/dev/null || { echo "缺少 uv，请先安装 uv。" >&2; exit 1; }
if [[ ! -x "$root_dir/.venv/bin/xcore-controller" || ! -x "$root_dir/.venv/bin/python" ]]; then
    echo "准备本地 controller Python 3.11 环境。"
    uv sync --project "$root_dir" --python 3.11 --locked --no-dev
fi
config_shell="$("$root_dir/.venv/bin/python" "$root_dir/tools/config_defaults.py" --shell)"
eval "$config_shell"
[[ -n "$task" ]] || task="$XCORE_TASK"
controller_url="http://127.0.0.1:$XCORE_CONTROLLER_SERVICE_PORT"
leader_url="http://127.0.0.1:$XCORE_GELLO_SERVICE_PORT"

run() { "$root_dir/.venv/bin/xcore-controller" "$@"; }
remote_call() { run command "$controller_url" "$@"; }
json() { "$root_dir/.venv/bin/python" -m json.tool; }

mkdir -p "$root_dir/logs"
exec 9>"$root_dir/logs/.remote-record.lock"
flock -n 9 || { echo "已有远端数采入口正在运行。" >&2; exit 1; }
session_logs="$(mktemp -d "$root_dir/logs/remote-record-$(date +%Y%m%d-%H%M%S)-XXXXXX")"
echo "本次启动日志：$session_logs"
export XCORE_SESSION_LOG_DIR="$session_logs"

bridge_pid=""
web_pid=""
watch_pid=""
gello_pid=""
tunnel_pid=""
dataset_pid=""
episode_active=false
session_started=false
armed=false
saved_tty=""
pending_key=""

# A synchronous save can take seconds. Preserve one intentional R/Q typed while
# busy, discard repeated S/D, and do not turn those repeats into new operations.
collect_pending_keys() {
    [[ -t 0 ]] || return 0
    local queued
    while IFS= read -r -t 0.02 -n1 queued; do
        case "${queued,,}" in
            q) pending_key=q ;;
            r) [[ "$pending_key" == q ]] || pending_key=r ;;
            *) ;;
        esac
    done
    return 0
}

cleanup() {
    local exit_status=$?
    trap - EXIT
    set +e
    if [[ -n "$saved_tty" ]]; then
        stty "$saved_tty"
    fi
    if [[ -n "$watch_pid" ]]; then
        kill "$watch_pid" 2>/dev/null
        wait "$watch_pid" 2>/dev/null
    fi
    if [[ "$episode_active" == true ]]; then
        echo "退出：当前 episode 未保存，按丢弃处理。"
        if ! remote_call episode/discard --reason "script exit" >/dev/null; then
            exit_status=1
        fi
    fi
    if [[ "$armed" == true ]]; then
        echo "退出处理（返回模式 $XCORE_RETURN_MODE）。"
        if remote_call exit --return-mode "$XCORE_RETURN_MODE" >/dev/null; then
            echo "远端退出处理完成。"
        else
            echo "退出返回失败：请先查看远端状态和控制器日志，勿重复发送运动命令。" >&2
            exit_status=1
        fi
    fi
    if [[ "$session_started" == true ]]; then
        if ! remote_call session/stop >/dev/null; then
            exit_status=1
        fi
    fi
    if [[ -n "$web_pid" ]]; then
        kill "$web_pid" 2>/dev/null
        wait "$web_pid" 2>/dev/null
    fi
    if [[ -n "$bridge_pid" ]]; then
        kill "$bridge_pid" 2>/dev/null
        wait "$bridge_pid" 2>/dev/null
    fi
    # setsid creates a private process group; stop only children we started.
    for owned_pid in "$dataset_pid" "$tunnel_pid" "$gello_pid"; do
        if [[ -n "$owned_pid" ]]; then
            kill -TERM -- "-$owned_pid" 2>/dev/null
            wait "$owned_pid" 2>/dev/null
        fi
    done
    exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$auto_start" == true ]]; then
    command -v setsid >/dev/null || { echo "缺少 setsid（util-linux）。" >&2; exit 1; }
    echo "[1/5] 远端 hardware API 与连接"
    if ! curl -fsS --max-time 2 "$controller_url/status" >/dev/null 2>&1; then
        setsid "$root_dir/scripts/start_remote_controller.sh" --hardware \
            >"$session_logs/controller.log" 2>&1 9>&- &
        tunnel_pid=$!
    fi
    run setup-session controller || {
        [[ ! -f "$session_logs/controller.log" ]] || tail -n 20 "$session_logs/controller.log" >&2
        exit 1
    }
    echo "[2/5] 夹爪 API（此阶段只读，不激活）"
    if [[ "$XCORE_FOLLOW_GRIPPER" == true ]]; then
        run setup-session gripper
    fi
    echo "[3/5] 本地 GELLO 七通道"
    if ! curl -fsS --max-time 2 "$leader_url/sample" >/dev/null 2>&1; then
        [[ -e "$XCORE_GELLO_PORT" ]] || {
            echo "GELLO 串口不存在：$XCORE_GELLO_PORT；请连接 USB 数据线及主臂电源。" >&2
            exit 1
        }
        setsid "$root_dir/scripts/start_gello_service.sh" \
            >"$session_logs/gello.log" 2>&1 9>&- &
        gello_pid=$!
    fi
    run setup-session leader || {
        [[ ! -f "$session_logs/gello.log" ]] || tail -n 20 "$session_logs/gello.log" >&2
        exit 1
    }
    echo "[4/5] 两台 RGBD 相机与预览连接"
    run setup-session cameras
    echo "[5/5] 数据浏览服务"
    if ! curl -fsS --max-time 2 "http://127.0.0.1:$XCORE_DATASET_SERVICE_PORT/api/datasets" >/dev/null 2>&1; then
        setsid "$root_dir/scripts/start_dataset.sh" \
            >"$session_logs/dataset.log" 2>&1 9>&- &
        dataset_pid=$!
    fi
    run setup-session dataset || {
        [[ ! -f "$session_logs/dataset.log" ]] || tail -n 20 "$session_logs/dataset.log" >&2
        exit 1
    }
else
    run setup-session controller
    run setup-session leader
fi

if [[ "$check_only" == true ]]; then
    echo "服务检查完成，未激活夹爪、未上电或发送运动目标。"
    exit 0
fi
if [[ "$enable_motion" != true ]]; then
    echo "未授权运动：可以查看状态，开始记录需使用 --enable-motion 并现场确认。"
fi

if [[ -x "$root_dir/.venv/bin/xcore-controller" ]]; then
    "$root_dir/.venv/bin/xcore-controller" bridge \
        --leader-url "$leader_url" --remote-url "$controller_url" &
else
    run bridge --leader-url "$leader_url" --remote-url "$controller_url" &
fi
bridge_pid=$!
sleep 1

if [[ "$web" == true ]]; then
    web_args=(
        web --controller-url "$controller_url"
        --cam1-url "$XCORE_CAM1_URL" --cam2-url "$XCORE_CAM2_URL"
        --dataset-url "http://127.0.0.1:$XCORE_DATASET_SERVICE_PORT/edit-dataset"
        --task "$task" --return-mode "$XCORE_RETURN_MODE"
    )
    [[ "$enable_motion" == true ]] && web_args+=(--allow-motion)
    [[ -z "$web_port" ]] || web_args+=(--port "$web_port")
    echo "网页数采模式：运动$([[ "$enable_motion" == true ]] && echo 已授权 || echo 未授权)。"
    if [[ -x "$root_dir/.venv/bin/xcore-controller" ]]; then
        "$root_dir/.venv/bin/xcore-controller" "${web_args[@]}" &
    else
        run "${web_args[@]}" &
    fi
    web_pid=$!
    wait "$web_pid"
    exit $?
fi

if [[ "$enable_motion" == true ]]; then
    echo "即将按需激活夹爪、执行对齐（prepare）并进入实时跟随。"
    echo "请保持 GELLO 静止，确认 CR7 运动路径及夹爪周围安全。"
    read -r -p "输入 y 继续: " answer
    if [[ "$answer" != y && "$answer" != Y ]]; then
        echo "已取消（未运动）。"
        exit 1
    fi
    if [[ "$XCORE_FOLLOW_GRIPPER" == true ]]; then
        run setup-session gripper --activate | json
    fi
    if [[ "$prepare" == true ]]; then
        echo "正在对齐（prepare），可能需要数分钟；此终端会等待，请勿关闭。"
        remote_call prepare | json
    fi
    echo "对齐完成，正在 arm（进入实时跟随）。"
    remote_call arm | json
    armed=true
    "$root_dir/.venv/bin/xcore-controller" watch-motion "$controller_url" &
    watch_pid=$!
    echo "六轴 RT 和夹爪反馈均已就绪，持续监测远端停止原因。"
fi

remote_call session/start --task "$task" | json >/dev/null
session_started=true
echo "会话已创建，任务：$task"
echo "按键：R 开始记录 | S 保存 | D 丢弃 | P 位姿 | Q 退出 | H 帮助（无需回车）"
if [[ -t 0 ]]; then
    saved_tty="$(stty -g)"
    stty -icanon -echo -ixon min 1 time 0
fi

while true; do
    if [[ "$armed" == true ]] && {
        ! kill -0 "$bridge_pid" 2>/dev/null || ! kill -0 "$watch_pid" 2>/dev/null;
    }; then
        echo "跟随已异常停止或数据桥退出；本次退出不自动返回，请查看上方故障原因。" >&2
        armed=false
        remote_call stop >/dev/null || true
        exit 1
    fi
    if [[ -n "$pending_key" ]]; then
        key="$pending_key"
        pending_key=""
    elif read -r -t 0.5 -n1 -s key; then
        :
    else
        read_status=$?
        (( read_status == 1 )) && break  # EOF; timeout keeps checking health.
        continue
    fi
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
            echo "[记录] 正在保存：等待双 RGBD 落盘、校验并封存；跟随继续，请稍候。"
            episode_active=false
            remote_call episode/save | json
            collect_pending_keys
            echo "[记录] 保存完成。按 R 开始下一段，或按 Q 结束会话。"
            ;;
        d)
            [[ "$episode_active" == true ]] || { echo "没有活动 episode。" >&2; continue; }
            echo "[记录] 正在丢弃当前片段，请稍候。"
            episode_active=false
            remote_call episode/discard --reason "operator discard" | json
            collect_pending_keys
            echo "[记录] 已丢弃。按 R 开始下一段，或按 Q 结束会话。"
            ;;
        p) remote_call pose | json ;;
        h|'?')
            echo "R 开始，S 保存，D 丢弃，P 位姿，Q 退出"
            ;;
        q) break ;;
        *) ;;
    esac
done
