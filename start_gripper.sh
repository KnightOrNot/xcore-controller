#!/usr/bin/env bash
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
gripper_host="${XCORE_GRIPPER_HOST:-192.168.2.225}"
ssh_user="${XCORE_GRIPPER_SSH_USER:-rokae}"
action=start
reset_stream=false
local_mode=false
serial_port="${GRIPPER_SERIAL_PORT:-}"
local_options=()

usage() {
    cat <<'EOF'
用法：./start_gripper.sh [选项]
默认通过 SSH 启动远端 .225 的后台夹爪服务并检查 TCP:5005，不打开本机串口。
启动时会在确认没有跟随／回零任务后自动清除单纯的断流超时锁定。
  --gripper-host HOST  远端地址，默认 192.168.2.225
  --ssh-user USER     远端用户名，默认 rokae
  --status            仅检查 TCP 服务，不启动或重启
  --restart           重启远端服务（先结束跟随；重启会激活夹爪）
  --reset-stream      发送 stop 清除断流故障（先结束跟随）
  --local             夹爪 USB 实际接在本机时启动本机服务
  --serial-port PATH  本机模式的明确夹爪串口；此参数也会启用本机模式
  --host IP / --port N / --no-activate  仅本机服务参数
  -h, --help          显示帮助
EOF
}
fail() { echo "错误：$*" >&2; exit 1; }

while (( $# )); do
    case "$1" in
        --gripper-host) gripper_host="${2:?缺少远端地址}"; shift 2 ;;
        --ssh-user) ssh_user="${2:?缺少用户名}"; shift 2 ;;
        --status) action=status; shift ;;
        --restart) action=restart; shift ;;
        --reset-stream) reset_stream=true; shift ;;
        --local) local_mode=true; shift ;;
        --serial-port) serial_port="${2:?缺少夹爪串口}"; local_mode=true; shift 2 ;;
        --host|--port)
            [[ $# -ge 2 ]] || fail "$1 缺少参数"
            local_options+=("$1" "$2"); local_mode=true; shift 2 ;;
        --no-activate) local_options+=("$1"); local_mode=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "未知参数：$1" ;;
    esac
done

if [[ "$local_mode" == true ]]; then
    [[ "$action" == start && "$reset_stream" == false ]] || fail "远端管理参数不能用于本机模式"
    [[ -n "$serial_port" ]] || fail "本机模式必须指定 --serial-port；当前夹爪在 .225，请直接运行 ./start_gripper.sh"
    [[ -e "$serial_port" ]] || fail "夹爪串口不存在：$serial_port"
    gello_port="${XCORE_GELLO_PORT:-/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTB4C7PQ-if00-port0}"
    if [[ -e "$gello_port" && "$(readlink -f -- "$serial_port")" == "$(readlink -f -- "$gello_port")" ]]; then
        fail "指定的是 GELLO 主臂串口，不能用于 Robotiq 夹爪：$serial_port"
    fi
    exec bash "$root_dir/xcore-gripper-2F85/run_gripper.sh" \
        --serial-port "$serial_port" "${local_options[@]}"
fi

[[ "$gripper_host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.:-]*$ ]] || fail "远端地址格式不正确"
[[ "$ssh_user" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || fail "SSH 用户名格式不正确"
[[ "$action" != status || "$reset_stream" == false ]] || fail "--status 是只读检查，不能与 --reset-stream 同时使用"
python="$root_dir/xcore-sdk-python/.venv/bin/python"
[[ -x "$python" ]] || fail "请先运行 ./setup.sh 安装 SDK 环境"
if [[ "$action" == restart ]]; then
    exec 9>"$root_dir/xcore-sdk-python/.follow.lock"
    flock -n 9 || fail "已有跟随／回零任务运行；先结束实验再重启夹爪服务"
fi
if [[ "$action" != status ]]; then
    command -v ssh >/dev/null || fail "未安装 SSH 客户端"
    echo "远端夹爪：$gripper_host:5005，服务操作：$action"
    ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 \
        "$ssh_user@$gripper_host" "systemctl --user $action xcore-gripper-follow.service" 9>&-
fi

"$python" - "$gripper_host" "$reset_stream" "$action" "$root_dir/xcore-sdk-python/.follow.lock" 9>&- <<'PY'
import fcntl
import json
import sys
import time
from xcore_sdk_python.gripper_follow import GripperFollowClient, GripperStreamFault

host, reset, action, lock_path = sys.argv[1:]
client = GripperFollowClient(host, 5005, 1)
deadline = time.monotonic() + (15 if action != "status" else 0)

def stop_idle_stream():
    with open(lock_path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("已有跟随／回零任务运行，未发送夹爪 stop；请等待实验退出") from error
        client.request("stop")
        return client.check()

try:
    while True:
        try:
            if reset == "true":
                state = stop_idle_stream()
            else:
                try:
                    state = client.check()
                except GripperStreamFault as error:
                    if action != "start" or error.reason != "Gripper target stream timed out":
                        raise
                    state = stop_idle_stream()
                    print("已清除上次退出留下的夹爪断流超时；未重启或重新激活夹爪。")
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
    print("远端夹爪服务已就绪：" + json.dumps(state, ensure_ascii=False))
except Exception as error:
    print(f"夹爪检查失败：{error}", file=sys.stderr)
    if "stream fault" in str(error):
        print("先结束统一跟随，再运行 ./start_gripper.sh --reset-stream 清除断流故障。", file=sys.stderr)
    sys.exit(1)
PY
