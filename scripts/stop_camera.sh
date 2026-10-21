#!/usr/bin/env bash
# Stop remote API processes and close only this project's camera SSH tunnels.
set -Eeuo pipefail
scripts_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$scripts_dir/.." && pwd)"

# 默认参数来自 config/default.toml；已存在的 XCORE_* 环境变量优先。
config_python="$root_dir/xcore-sdk-python/.venv/bin/python"
[[ -x "$config_python" ]] || config_python="$(command -v python3 || true)"
if [[ -f "$root_dir/config/default.toml" || -f "$root_dir/tools/config_defaults.py" ]]; then
    [[ -n "$config_python" ]] || { echo '缺少 Python 3.11+，无法读取 config/default.toml' >&2; exit 1; }
    config_arguments=("$root_dir/tools/config_defaults.py" --shell)
    [[ -z "${XCORE_CONFIG:-}" ]] || config_arguments+=(--config "$XCORE_CONFIG")
    config_shell="$("$config_python" "${config_arguments[@]}")" || {
        echo '读取 config/default.toml 失败' >&2; exit 1;
    }
    eval "$config_shell"
fi

camera=all
ssh_target="${XCORE_CAMERA_SSH_TARGET:-rokae@192.168.2.225}"
port_options=()
usage() {
    cat <<'EOF'
用法：./scripts/stop_camera.sh [--camera all|cam1|cam2] [--ssh-target USER@HOST]
完全停止远端相机服务、释放设备，并关闭对应的本地 SSH 隧道，默认停止两台。
  --local-port N / --remote-port N  自定义隧道端口；仅单台时使用，需与启动参数一致
只停止采集、保留 API 服务时，使用 ./scripts/start_camera.sh stop。
不会停止夹爪或机械臂服务，也不会重新启用开机自启。
EOF
}
fail() { echo "错误：$*" >&2; exit 1; }
while (( $# )); do
    case "$1" in
        --camera) camera="${2:?缺少相机名称}"; shift 2 ;;
        --ssh-target) ssh_target="${2:?缺少 SSH 目标}"; shift 2 ;;
        --local-port|--remote-port)
            value="${2:?缺少端口}"
            [[ "$value" =~ ^[0-9]{1,5}$ ]] || fail "端口必须为 1～65535 的整数"
            (( 10#$value >= 1 && 10#$value <= 65535 )) || fail "端口必须为 1～65535 的整数"
            port_options+=("$1" "$((10#$value))"); shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "未知参数：$1" ;;
    esac
done
[[ "$ssh_target" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || fail "SSH 目标必须为 user@hostname 或 user@IPv4"
case "$camera" in
    all)
        (( ${#port_options[@]} == 0 )) || fail "自定义端口需要 --camera cam1 或 cam2"
        units=(camera-realsense-d435i@cam1.service camera-realsense-d435i@cam2.service) ;;
    cam1|cam2) units=("camera-realsense-d435i@$camera.service") ;;
    *) fail "相机必须是 all、cam1 或 cam2" ;;
esac
command -v ssh >/dev/null || fail "未安装 SSH 客户端"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
    -o ConnectTimeout="${XCORE_SSH_CONNECT_TIMEOUT:-5}" \
    "$ssh_target" "systemctl --user stop ${units[*]} && systemctl --user show ${units[*]} -p Id -p ActiveState -p MainPID"
echo "远端相机服务已停止，正在清理对应本地隧道。"
bash "$scripts_dir/start_camera.sh" disconnect --camera "$camera" \
    --ssh-target "$ssh_target" "${port_options[@]}"
