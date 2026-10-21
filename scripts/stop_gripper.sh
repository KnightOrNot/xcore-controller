#!/usr/bin/env bash
# Stop only the remote gripper service, after the follow session has exited.
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
gripper_host="${XCORE_GRIPPER_HOST:-192.168.2.225}"
ssh_user="${XCORE_GRIPPER_SSH_USER:-rokae}"
usage() {
    cat <<'EOF'
用法：./scripts/stop_gripper.sh [--gripper-host HOST] [--ssh-user USER]
停止远端 xcore-gripper-follow.service，释放夹爪串口，不执行夹爪开合。
必须先结束跟随／记录并等待退出返回完成；本地跟随锁占用时拒绝停止。
默认 rokae@192.168.2.225，也可设置 XCORE_GRIPPER_HOST、XCORE_GRIPPER_SSH_USER。
EOF
}
fail() { echo "错误：$*" >&2; exit 1; }
while (( $# )); do
    case "$1" in
        --gripper-host) gripper_host="${2:?缺少远端地址}"; shift 2 ;;
        --ssh-user) ssh_user="${2:?缺少用户名}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "未知参数：$1" ;;
    esac
done
[[ "$gripper_host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.:-]*$ ]] || fail "远端地址格式不正确"
[[ "$ssh_user" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || fail "SSH 用户名格式不正确"
command -v ssh >/dev/null || fail "未安装 SSH 客户端"
command -v flock >/dev/null || fail "未安装 flock"
[[ -d "$root_dir/xcore-sdk-python" ]] || fail "SDK 子模块目录缺失，无法核对跟随锁"
exec 9>"$root_dir/xcore-sdk-python/.follow.lock"
flock -n 9 || fail "已有跟随／退出返回任务运行；请先结束实验并等待退出"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 \
    "$ssh_user@$gripper_host" \
    'systemctl --user stop xcore-gripper-follow.service && systemctl --user show xcore-gripper-follow.service -p ActiveState -p MainPID' 9>&-
echo "远端夹爪服务已停止；可用 ./scripts/start_gripper.sh 再次启动。"
