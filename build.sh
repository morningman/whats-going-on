#!/usr/bin/env bash
#
# build.sh — 构建 Email Watcher 并将所有运行所需文件打包到 output/ 目录
# 兼容 macOS 和 Linux
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/output"
VENV_DIR="${OUTPUT_DIR}/venv"

echo "=============================="
echo "  Email Watcher — Build"
echo "=============================="
echo ""

# ─── 1. 检查 Python 环境 ───
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        # 确保是 Python 3
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

echo "✅ Python: $($PYTHON --version)"

# ─── 2. 清理并创建 output 目录 ───
echo ""
echo "📁 准备 output 目录..."
if [ -d "$OUTPUT_DIR" ]; then
    echo "   清理旧的 output 目录..."
    rm -rf "$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR"

# ─── 3. 复制项目文件 ───
echo "📦 复制项目文件..."

# 复制 Python 源码
cp "$SCRIPT_DIR/app.py" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/asf_auth.py" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/summarizer.py" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$OUTPUT_DIR/"

# 复制 fetchers 模块
mkdir -p "$OUTPUT_DIR/fetchers"
cp "$SCRIPT_DIR/fetchers/__init__.py" "$OUTPUT_DIR/fetchers/"
cp "$SCRIPT_DIR/fetchers/ponymail.py" "$OUTPUT_DIR/fetchers/"
cp "$SCRIPT_DIR/fetchers/pipermail.py" "$OUTPUT_DIR/fetchers/"

# 复制前端静态文件
mkdir -p "$OUTPUT_DIR/static"
cp "$SCRIPT_DIR/static/style.css" "$OUTPUT_DIR/static/"
cp "$SCRIPT_DIR/static/app.js" "$OUTPUT_DIR/static/"
cp "$SCRIPT_DIR/static/settings.js" "$OUTPUT_DIR/static/"

# 复制 HTML 模板
mkdir -p "$OUTPUT_DIR/templates"
cp "$SCRIPT_DIR/templates/index.html" "$OUTPUT_DIR/templates/"
cp "$SCRIPT_DIR/templates/settings.html" "$OUTPUT_DIR/templates/"

# 复制配置模板
cp "$SCRIPT_DIR/config.example.json" "$OUTPUT_DIR/"

# 如果存在用户配置，也复制过去
if [ -f "$SCRIPT_DIR/config.json" ]; then
    echo "   复制用户配置 config.json..."
    cp "$SCRIPT_DIR/config.json" "$OUTPUT_DIR/"
fi

# 创建数据目录
mkdir -p "$OUTPUT_DIR/data/emails"
mkdir -p "$OUTPUT_DIR/data/digests"
mkdir -p "$OUTPUT_DIR/log"

echo "   ✅ 文件复制完成"

# ─── 4. 创建虚拟环境并安装依赖 ───
echo ""
echo "🐍 创建 Python 虚拟环境..."
"$PYTHON" -m venv "$VENV_DIR"

# 激活虚拟环境（兼容不同 shell）
source "$VENV_DIR/bin/activate"

echo "📥 安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r "$OUTPUT_DIR/requirements.txt" -q

echo "   ✅ 依赖安装完成"

deactivate

# ─── 5. 复制 run.sh 到 output ───
echo ""
echo "📋 复制启动脚本..."
cp "$SCRIPT_DIR/run.sh" "$OUTPUT_DIR/run.sh"
chmod +x "$OUTPUT_DIR/run.sh"

# ─── 6. 完成 ───
echo ""
echo "=============================="
echo "  ✅ 构建完成！"
echo "=============================="
echo ""
echo "输出目录: $OUTPUT_DIR"
echo ""
echo "使用方式:"
echo "  cd output"
echo "  ./run.sh start       # 启动服务"
echo "  ./run.sh stop        # 停止服务"
echo "  ./run.sh status      # 查看状态"
echo "  ./run.sh restart     # 重启服务"
echo ""
echo "首次使用请先配置:"
echo "  1. cp config.example.json config.json"
echo "  2. 编辑 config.json 填入 Claude API Key"
echo "  3. 或启动后访问 http://localhost:5000/settings 在线配置"
echo ""
