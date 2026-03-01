#!/usr/bin/env bash
#
# dev.sh — What's Going On 统一开发/运行脚本
# 直接从源码目录运行，智能管理 Python 虚拟环境
#
# 用法:
#   ./dev.sh start   [--port PORT] [--host HOST]   启动服务
#   ./dev.sh stop                                   停止服务
#   ./dev.sh restart [--port PORT] [--host HOST]   重启服务
#   ./dev.sh status                                 查看服务状态
#   ./dev.sh logs    [-f]                           查看日志
#   ./dev.sh setup                                  仅初始化/更新 venv
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PID_FILE="${SCRIPT_DIR}/.email-watcher.pid"
LOG_DIR="${SCRIPT_DIR}/log"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"
REQ_HASH_FILE="${VENV_DIR}/.requirements.hash"

# 默认参数
HOST="0.0.0.0"
PORT="5000"
FOLLOW_LOGS="false"

# ─── 工具函数 ───

print_usage() {
    echo "What's Going On — 开发/运行脚本"
    echo ""
    echo "用法: $0 {start|stop|restart|status|logs|setup} [选项]"
    echo ""
    echo "命令:"
    echo "  start     启动服务（自动初始化环境）"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  status    查看服务状态"
    echo "  logs      查看运行日志"
    echo "  setup     仅初始化/更新虚拟环境（不启动服务）"
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

# 计算 requirements.txt 的校验和（兼容 macOS 和 Linux）
calc_hash() {
    if command -v md5sum &>/dev/null; then
        md5sum "$REQ_FILE" | cut -d' ' -f1
    elif command -v md5 &>/dev/null; then
        md5 -q "$REQ_FILE"
    else
        # 回退方案：用文件修改时间
        stat -f "%m" "$REQ_FILE" 2>/dev/null || stat -c "%Y" "$REQ_FILE" 2>/dev/null
    fi
}

# ─── 环境管理 ───

ensure_venv() {
    # 1. 检查 Python 3
    local PYTHON=""
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local version major
            version=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
            major=$(echo "$version" | cut -d. -f1)
            if [ "$major" = "3" ]; then
                PYTHON="$candidate"
                break
            fi
        fi
    done

    if [ -z "$PYTHON" ]; then
        echo "❌ 未找到 Python 3，请先安装 Python 3.10+"
        exit 1
    fi

    # 2. 创建 venv（如果不存在）
    if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/python" ]; then
        echo "🐍 创建 Python 虚拟环境..."
        "$PYTHON" -m venv "$VENV_DIR"
        echo "   ✅ 虚拟环境创建完成"
        # 强制安装依赖
        install_deps
        return
    fi

    # 3. 检查依赖是否需要更新
    local current_hash
    current_hash=$(calc_hash)
    local saved_hash=""
    if [ -f "$REQ_HASH_FILE" ]; then
        saved_hash=$(cat "$REQ_HASH_FILE")
    fi

    if [ "$current_hash" != "$saved_hash" ]; then
        echo "📦 检测到 requirements.txt 变更，更新依赖..."
        install_deps
    else
        echo "✅ 虚拟环境就绪（依赖无变更，跳过安装）"
    fi
}

install_deps() {
    echo "📥 安装 Python 依赖..."
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE" -q
    # 保存 hash
    calc_hash > "$REQ_HASH_FILE"
    echo "   ✅ 依赖安装完成"
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

do_setup() {
    echo "=============================="
    echo "  What's Going On — Setup"
    echo "=============================="
    echo ""
    ensure_venv
    echo ""
    echo "✅ 环境初始化完成"
}

do_start() {
    echo "=============================="
    echo "  What's Going On — Start"
    echo "=============================="
    echo ""

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "⚠️  服务已在运行中 (PID: $pid)"
        echo "   访问 http://${HOST}:${PORT}"
        exit 0
    fi

    ensure_venv
    check_config

    echo ""
    echo "🚀 启动 What's Going On..."
    echo "   Host: $HOST"
    echo "   Port: $PORT"
    echo "   日志目录: $LOG_DIR"
    echo ""

    # 创建运行时目录
    mkdir -p "$LOG_DIR"
    mkdir -p "$SCRIPT_DIR/data/emails"
    mkdir -p "$SCRIPT_DIR/data/digests"
    mkdir -p "$SCRIPT_DIR/data/cache/emails"
    mkdir -p "$SCRIPT_DIR/data/cache/github"
    mkdir -p "$SCRIPT_DIR/data/summaries"

    # 直接从源码目录启动 Flask
    (
        cd "$SCRIPT_DIR"
        export FLASK_APP=app.py
        nohup "$VENV_DIR/bin/python" -c "
from app import app, setup_logging, auto_login_asf
setup_logging('${LOG_DIR}')
auto_login_asf()
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
        rm -f "$PID_FILE"
        exit 1
    fi
}

do_stop() {
    echo "=============================="
    echo "  What's Going On — Stop"
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
    echo "  What's Going On — Status"
    echo "=============================="
    echo ""

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "🟢 服务运行中"
        echo "   PID:  $pid"
        echo "   地址: http://localhost:${PORT}"
        echo ""
        if command -v ps &>/dev/null; then
            echo "   进程信息:"
            ps -p "$pid" -o pid,ppid,%cpu,%mem,etime,command 2>/dev/null | head -5 || true
        fi
    else
        echo "🔴 服务未运行"
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
    echo "   app.log      — 应用详细日志"
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
    setup)
        do_setup
        ;;
    *)
        echo "❌ 未知命令: $COMMAND"
        echo ""
        print_usage
        exit 1
        ;;
esac
