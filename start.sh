#!/bin/bash
# Created by 小杜 on 2026/08

# 芮拓面板 Linux 启动脚本
set -e
cd "$(dirname "$0")/backend"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未检测到 python3，请先安装 Python 3.8+"
    exit 1
fi

if [ ! -d ".deps/fastapi" ]; then
    echo "[*] 首次运行：正在安装依赖..."
    python3 -m pip install -r requirements.txt --target .deps || {
        echo "[*] 尝试使用国内镜像..."
        python3 -m pip install -r requirements.txt --target .deps -i https://pypi.tuna.tsinghua.edu.cn/simple
    }
fi

echo "[*] 芮拓面板启动中: http://127.0.0.1:8000"
exec python3 run.py
