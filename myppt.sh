#!/bin/sh
# 用法：sh myppt.sh 命令 参数…（命令见 run.py）
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || command -v python)"
[ -z "$PY" ] && { echo "找不到 Python 3.8+，请先安装"; exit 1; }
exec "$PY" "$HERE/run.py" "$@"
