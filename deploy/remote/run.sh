#!/bin/sh
# ELN 运维受限执行器
#
# 部署位置：生产机 10.249.132.143:/opt/opsbot/run.sh
# 属主：root，权限 0755
# 调用方：机器人专用 SSH 密钥，authorized_keys 里用 command= 锁定只能跑本脚本
#
# 设计原则：
#   1. 只认模板 ID，不认任意命令
#   2. 参数个数与取值都在脚本内校验，不看调用方给的是什么
#   3. 任何未识别的输入一律 exit 64，绝不"尽力执行"

set -eu

# ── 白名单 ────────────────────────────────────────────────
case "${1:-}" in
    container_status|container_logs|cron_list|disk_usage) ;;
    *)
        echo "denied: unknown template '${1:-}'" >&2
        exit 64
        ;;
esac

TEMPLATE="$1"
shift

# 容器名白名单
check_container() {
    case "${1:-}" in
        xdraw-api|xdraw-worker|xdraw-scheduler|xdraw-web) ;;
        *)
            echo "denied: container '$1' not in allowlist" >&2
            exit 64
            ;;
    esac
}

# 行数校验：必须是 1..2000 的纯数字
check_lines() {
    case "${1:-}" in
        ''|*[!0-9]*)
            echo "denied: lines must be digits" >&2
            exit 64
            ;;
    esac
    if [ "$1" -lt 1 ] || [ "$1" -gt 2000 ]; then
        echo "denied: lines out of range 1..2000" >&2
        exit 64
    fi
}

case "$TEMPLATE" in
    container_status)
        [ $# -eq 1 ] || { echo "denied: container_status takes 1 arg" >&2; exit 64; }
        check_container "$1"
        exec docker ps -a --filter "name=^$1$" --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
        ;;
    container_logs)
        [ $# -eq 2 ] || { echo "denied: container_logs takes 2 args" >&2; exit 64; }
        check_container "$1"
        check_lines "$2"
        exec docker logs --tail "$2" --timestamps "$1" 2>&1
        ;;
    cron_list)
        [ $# -eq 0 ] || { echo "denied: cron_list takes no args" >&2; exit 64; }
        exec crontab -l 2>&1
        ;;
    disk_usage)
        [ $# -eq 0 ] || { echo "denied: disk_usage takes no args" >&2; exit 64; }
        echo "--- df -h ---"
        df -h 2>&1
        echo "--- docker system df ---"
        docker system df 2>&1
        ;;
esac
