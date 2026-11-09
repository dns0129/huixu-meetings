#!/bin/zsh
set -e
cd "$(dirname "$0")"
ROOT_DIR="$PWD"
printf '\n会序 · 会议素材工作台\n\n'
if ! command -v python3 >/dev/null; then
  printf '未找到 Python 3，请先安装 Python 3。\n'
  read -r '?按回车退出…'
  exit 1
fi
PYTHON_CMD="$(command -v python3)"
if ! "$PYTHON_CMD" -c 'import flask,openpyxl,docx,PIL,certifi,pypdf' >/dev/null 2>&1; then
  if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then "$PYTHON_CMD" -m venv "$ROOT_DIR/.venv"; fi
  PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
  if ! "$PYTHON_CMD" -c 'import flask,openpyxl,docx,PIL,certifi,pypdf' >/dev/null 2>&1; then
    printf '正在为本项目安装 Python 依赖…\n'
    "$PYTHON_CMD" -m pip install -r "$ROOT_DIR/requirements.txt"
  fi
fi
if [ ! -x "$ROOT_DIR/.pi-runtime/node_modules/.bin/pi" ]; then
  if command -v npm >/dev/null; then
    printf '正在安装本项目的 Pi 和生图扩展…\n'
    npm ci --prefix "$ROOT_DIR/.pi-runtime" --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org
  else
    printf '未找到 Node.js；普通物料仍可使用，Pi AI 需要安装 Node.js 22.19 以上版本。\n'
  fi
fi
if curl -fsS http://127.0.0.1:8765/api/session >/dev/null 2>&1; then
  printf '会序已经在运行，正在打开页面。\n'
  open http://127.0.0.1:8765/
  exit 0
fi
"$PYTHON_CMD" "$ROOT_DIR/app.py" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for i in {1..40}; do
  if curl -fsS http://127.0.0.1:8765/api/session >/dev/null 2>&1; then
    printf '已启动：http://127.0.0.1:8765/\n关闭此终端窗口将停止服务。\n'
    open http://127.0.0.1:8765/
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 0.25
done
printf '启动失败，请检查终端中的错误信息。\n'
wait "$SERVER_PID"
