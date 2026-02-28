#!/usr/bin/env bash
#
# run.sh — Email Watcher 启动/停止管理脚本
# 兼容 macOS 和 Linux
#
# 用法:
#   ./run.sh start   [--port PORT] [--host HOST]   启动服务
#   ./run.sh stop                                   停止服务
#   ./run.sh restart [--port PORT] [--host HOST]   重启服务
#   ./run.sh status                                 查看服务状态
#   ./run.sh logs                                   查看日志
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.email-watcher.pid"
LOG_DIR="$SCRIPT_DIR/log"
VENV_DIR="$SCRIPT_DIR/venv"

# 默认参数
HOST="0.0.0.0"
PORT="5000"

# ─── 工具函数 ───

print_usage() {
    echo "Email Watcher — 服务管理脚本"
    echo ""
    echo "用法: $0 {start|stop|restart|status|logs} [选项]"
    echo ""
    echo "命令:"
    echo "  start     启动服务"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  status    查看服务状态"
    echo "  logs      查看运行日志"
    echo ""
    echo "选项:"
    echo "  --port PORT   指定端口号 (默认: 5000)"
    echo "  --host HOST   指定绑定地址 (默认: 0.0.0.0)"
    echo "  -f, --follow  (logs 命令) 实时追踪日志"
    echo ""
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

is_running() {
    local pid
    pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "❌ 虚拟环境不存在: $VENV_DIR"
        echo "   请先运行 build.sh 构建项目"
        exit 1
    fi
}

check_config() {
    if [ ! -f "$SCRIPT_DIR/config.json" ]; then
        if [ -f "$SCRIPT_DIR/config.example.json" ]; then
            echo "⚠️  未找到 config.json，使用 config.example.json 作为默认配置"
            echo "   启动后请访问 http://${HOST}:${PORT}/settings 完成配置"
        fi
    fi
}

# ─── 命令实现 ───

do_start() {
    echo "=============================="
    echo "  Email Watcher — Start"
    echo "=============================="
    echo ""

    check_venv

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "⚠️  服务已在运行中 (PID: $pid)"
        echo "   访问 http://${HOST}:${PORT}"
        exit 0
    fi

    check_config

    echo "🚀 启动 Email Watcher..."
    echo "   Host: $HOST"
    echo "   Port: $PORT"
    echo "   日志目录: $LOG_DIR"
    echo ""

    # 创建日志目录
    mkdir -p "$LOG_DIR"

    # 激活虚拟环境并启动 Flask
    (
        source "$VENV_DIR/bin/activate"
        cd "$SCRIPT_DIR"
        export FLASK_APP=app.py
        nohup "$VENV_DIR/bin/python" -c "
from app import app, setup_logging
setup_logging('${LOG_DIR}')
app.run(host='${HOST}', port=${PORT}, debug=False)
" >> "$LOG_DIR/console.log" 2>&1 &
        echo $! > "$PID_FILE"
    )

    # 等待启动
    sleep 2

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "✅ 服务启动成功 (PID: $pid)"
        echo ""
        echo "   🌐 访问地址: http://localhost:${PORT}"
        echo "   ⚙️  设置页面: http://localhost:${PORT}/settings"
        echo "   📄 日志目录: $LOG_DIR"
        echo ""
        echo "   使用 '$0 stop' 停止服务"
        echo "   使用 '$0 logs' 查看日志"
        echo "   使用 '$0 logs -f' 实时追踪日志"
    else
        echo "❌ 服务启动失败，请查看日志:"
        echo "   cat $LOG_DIR/console.log"
        echo "   cat $LOG_DIR/app.log"
        # 清理 PID 文件
        rm -f "$PID_FILE"
        exit 1
    fi
}

do_stop() {
    echo "=============================="
    echo "  Email Watcher — Stop"
    echo "=============================="
    echo ""

    if ! is_running; then
        echo "ℹ️  服务未在运行"
        rm -f "$PID_FILE"
        return 0
    fi

    local pid
    pid=$(get_pid)
    echo "🛑 正在停止服务 (PID: $pid)..."

    # 先尝试优雅关闭
    kill "$pid" 2>/dev/null || true

    # 等待进程退出（最多 10 秒）
    local count=0
    while kill -0 "$pid" 2>/dev/null && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    # 如果还在运行，强制结束
    if kill -0 "$pid" 2>/dev/null; then
        echo "   ⚠️  优雅关闭超时，强制终止..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    rm -f "$PID_FILE"
    echo "✅ 服务已停止"
}

do_restart() {
    do_stop
    echo ""
    do_start
}

do_status() {
    echo "=============================="
    echo "  Email Watcher — Status"
    echo "=============================="
    echo ""

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "🟢 服务运行中"
        echo "   PID:  $pid"
        echo "   地址: http://localhost:${PORT}"
        echo ""

        # 显示进程信息（兼容 macOS 和 Linux）
        if command -v ps &>/dev/null; then
            echo "   进程信息:"
            ps -p "$pid" -o pid,ppid,%cpu,%mem,etime,command 2>/dev/null | head -5 || true
        fi
    else
        echo "🔴 服务未运行"
        # 清理残留的 PID 文件
        rm -f "$PID_FILE"
    fi
}

do_logs() {
    local APP_LOG="$LOG_DIR/app.log"
    if [ ! -f "$APP_LOG" ]; then
        echo "ℹ️  暂无日志文件"
        echo "   日志目录: $LOG_DIR"
        return
    fi

    echo "📄 日志目录: $LOG_DIR"
    echo "   app.log      — 应用详细日志（含 API 调用、邮件获取等）"
    echo "   console.log  — 控制台输出"
    echo "───────────────────────────────"

    if [ "$FOLLOW_LOGS" = "true" ]; then
        echo "   (实时追踪模式，Ctrl+C 退出)"
        echo ""
        tail -f "$APP_LOG"
    else
        echo "   (显示最近 50 行，使用 -f 参数实时追踪)"
        echo ""
        tail -50 "$APP_LOG"
    fi
}

# ─── 解析参数 ───

if [ $# -lt 1 ]; then
    print_usage
    exit 1
fi

COMMAND="$1"
shift

# 解析可选参数
FOLLOW_LOGS="false"
while [ $# -gt 0 ]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        -f|--follow)
            FOLLOW_LOGS="true"
            shift
            ;;
        *)
            echo "⚠️  未知参数: $1"
            print_usage
            exit 1
            ;;
    esac
done

# ─── 执行命令 ───

case "$COMMAND" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_restart
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    *)
        echo "❌ 未知命令: $COMMAND"
        echo ""
        print_usage
        exit 1
        ;;
esac
