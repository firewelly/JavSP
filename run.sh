#!/bin/bash
# JavSP 刮削器启动脚本（本地部署版）
# 用法: ~/JavSP_mac2/run.sh [扫描目录]
#   不带参数时使用 config.yml 中的 input_directory（当前: /Users/firewell/影视/AV）
# 注意: 需先启动 Clash Verge（代理 1080 端口）

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

# Clash Verge 未启动时自动拉起
if ! lsof -i :1080 -P 2>/dev/null | grep -q LISTEN; then
    echo "[run.sh] 代理端口 1080 未监听，正在启动 Clash Verge..."
    open -a "Clash Verge"
    for i in $(seq 1 15); do
        sleep 2
        lsof -i :1080 -P 2>/dev/null | grep -q LISTEN && break
    done
fi

# 选择解释器：优先用PATH里的python3（系统/Homebrew），依赖缺失时才回退
# 注意机器上可能有多个python3（如conda base）缺少confz等依赖，故此处逐个探测
# 可用 JAVSP_PYTHON 环境变量直接指定
PYTHON="${JAVSP_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    for candidate in \
        "$(command -v python3)" \
        "/opt/homebrew/bin/python3" \
        "/opt/homebrew/Caskroom/miniforge/base/envs/javsp_build/bin/python"
    do
        [ -x "$candidate" ] || continue
        if "$candidate" -c "import confz, playwright, lxml, PIL" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "[run.sh] 找不到依赖齐全的 Python 解释器（需要 confz/pydantic/playwright/lxml/pillow 等）"
    echo "[run.sh] 可执行: pip3 install -r requirements.txt && playwright install chromium"
    echo "[run.sh] 或用 JAVSP_PYTHON=/path/to/python 指定解释器"
    exit 1
fi
echo "[run.sh] 使用解释器: $PYTHON"

# 过滤 OneDrive PYTHONPATH 污染 + 自动回车确认番号
yes "" | "$PYTHON" -B -c "
import sys
sys.path = [p for p in sys.path if 'OneDrive' not in p]
from javsp.__main__ import entry
sys.argv = ['JavSP']
entry()
"
