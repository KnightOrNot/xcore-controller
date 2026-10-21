#!/usr/bin/env bash
# Manage remote cameras independently from arm/gripper following.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

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

camera_dir="$root_dir/camera-realsense-d435i"
camera=all
action=preview
action_set=false
extra=()
usage() {
    cat <<'EOF'
用法：./scripts/start_camera.sh [preview|connect|start|stop|status|info|snapshot|disconnect] [参数]
默认 preview，同时启动远端两台 D435i，各自打开 RGB＋深度页面，不控制机械臂或夹爪。
  --camera all|cam1|cam2  默认 all；cam1 端口 8086，cam2 端口 8087
  --no-open              preview 只打印页面网址，不打开浏览器
  --fps N                preview/start 的帧率；修改前先 stop
  --ssh-target USER@HOST preview/connect/disconnect 的远端主机
  --output DIR           snapshot 的本地保存目录，仅单台时可指定
其他参数转发给相机 CLI；单台端口覆盖时先指定 --camera。
关闭网页不会停止采集；请运行 ./scripts/start_camera.sh stop。
disconnect 只关闭隧道，不停止远端采集。
EOF
}
while (( $# )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --camera) camera="${2:?缺少相机名称}"; shift 2 ;;
        --ssh-target|--output|--url|--local-port|--remote-port|--fps|--width|--height|--jpeg-quality)
            extra+=("$1" "${2:?缺少参数值}"); shift 2 ;;
        preview|connect|start|stop|status|info|snapshot|disconnect)
            [[ "$action_set" == false ]] || { echo '只能指定一个操作' >&2; exit 2; }
            action="$1"; action_set=true; shift ;;
        *) extra+=("$1"); shift ;;
    esac
done
case "$camera" in
    all) cameras=(cam1 cam2) ;;
    cam1|cam2) cameras=("$camera") ;;
    *) echo '相机必须是 all、cam1 或 cam2' >&2; exit 2 ;;
esac
if [[ "$camera" == all ]]; then
    for option in "${extra[@]}"; do
        case "$option" in
            --output|--output=*|--url|--url=*|--local-port|--local-port=*|--remote-port|--remote-port=*)
                echo "参数 $option 需要明确指定 --camera cam1 或 cam2" >&2; exit 2 ;;
        esac
    done
fi
[[ -f "$camera_dir/pyproject.toml" ]] || {
    echo '相机子模块未初始化：git submodule update --init camera-realsense-d435i' >&2
    exit 1
}
if [[ -x "$camera_dir/.venv/bin/camera-realsense-d435i" ]]; then
    camera_command=("$camera_dir/.venv/bin/camera-realsense-d435i")
else
    command -v uv >/dev/null || { echo '请先安装 uv 并运行 ./scripts/setup.sh' >&2; exit 1; }
    camera_command=(uv run --locked --no-dev --project "$camera_dir" camera-realsense-d435i)
fi
snapshot_root="${XCORE_CAMERA_SNAPSHOT_DIR:-captures}"
[[ "$snapshot_root" == /* ]] || snapshot_root="$root_dir/$snapshot_root"
result=0
for selected in "${cameras[@]}"; do
    camera_options=("${extra[@]}")
    if [[ "$action" == snapshot ]]; then
        has_output=false
        for option in "${camera_options[@]}"; do
            [[ "$option" != --output && "$option" != --output=* ]] || has_output=true
        done
        [[ "$has_output" == true ]] || camera_options+=(--output "$snapshot_root/$selected/$(date +%Y%m%d-%H%M%S-%N)")
    fi
    echo "==> D435i $selected: $action"
    if "${camera_command[@]}" "$action" --camera "$selected" "${camera_options[@]}"; then
        :
    else
        result=1
    fi
done
exit "$result"
