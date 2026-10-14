#!/usr/bin/env bash
# 一键启动或重启本项目的 FastAPI 后端与 Vite 前端。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_PORT=8001
FRONTEND_PORT=3000
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

mkdir -p "$RUN_DIR"

usage() {
  echo "用法: ./restart.sh [start|stop|restart|status]"
  echo "默认执行 restart；如需指定 Python，可设置 BACKEND_PYTHON。"
}

read_pid() {
  local pid_file="$1"
  local pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(cat "$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$pid"
}

is_our_process() {
  local service="$1"
  local pid="$2"
  local command_line
  kill -0 "$pid" 2>/dev/null || return 1
  command_line="$(ps -p "$pid" -o command= 2>/dev/null)" || return 1
  if [[ "$service" == backend ]]; then
    [[ "$command_line" == *"uvicorn app:app"* && "$command_line" == *"--port $BACKEND_PORT"* ]]
  else
    [[ "$command_line" == *"vite/bin/vite.js"* && "$command_line" == *"--port $FRONTEND_PORT"* ]]
  fi
}

service_running() {
  local service="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")" || return 1
  is_our_process "$service" "$pid"
}

stop_service() {
  local service="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")" || {
    rm -f "$pid_file"
    echo "  $service 未由本脚本启动"
    return
  }
  if ! is_our_process "$service" "$pid"; then
    rm -f "$pid_file"
    echo "  $service 的 PID 文件已过期，未停止其他进程"
    return
  fi

  kill "$pid"
  for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "  $service 已停止 (PID: $pid)"
      return
    fi
    sleep 0.2
  done
  echo "  $service 未能正常退出 (PID: $pid)，请查看日志" >&2
  exit 1
}

port_is_busy() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | grep -q .
}

ensure_port_free() {
  local port="$1"
  if port_is_busy "$port"; then
    echo "端口 $port 已被其他进程占用；请先手动处理该进程。" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    exit 1
  fi
}

choose_python() {
  local candidate
  if [[ -n "${BACKEND_PYTHON:-}" ]]; then
    [[ -x "$BACKEND_PYTHON" ]] || {
      echo "BACKEND_PYTHON 不可执行: $BACKEND_PYTHON" >&2
      exit 1
    }
    printf '%s' "$BACKEND_PYTHON"
    return
  fi

  for candidate in \
    "$BACKEND_DIR/.venv/bin/python" \
    "$BACKEND_DIR/venv/bin/python"; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return
    fi
  done
  if [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]] &&
      "$CONDA_PREFIX/bin/python" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
    printf '%s' "$CONDA_PREFIX/bin/python"
    return
  fi

  if command -v conda >/dev/null 2>&1; then
    candidate="$(conda info --base 2>/dev/null)/envs/rag-src/bin/python"
    if [[ -x "$candidate" ]] && "$candidate" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return
    fi
  fi

  candidate="$(command -v python3 || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return
  fi
  echo "未找到 Python。请激活 rag-src 环境，或设置 BACKEND_PYTHON。" >&2
  exit 1
}

wait_for_url() {
  local url="$1"
  for _ in {1..60}; do
    if curl --noproxy '*' --silent --fail --max-time 2 "$url" >/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

start_services() {
  local python
  [[ -f "$BACKEND_DIR/.env" ]] || {
    echo "缺少 backend/.env；请先复制 backend/.env.example 并填写 API Key。" >&2
    exit 1
  }
  [[ -f "$FRONTEND_DIR/node_modules/vite/bin/vite.js" ]] || {
    echo "缺少前端依赖；请先运行: cd frontend && npm install" >&2
    exit 1
  }
  command -v node >/dev/null 2>&1 || {
    echo "未找到 Node.js；请先安装 Node.js。" >&2
    exit 1
  }
  command -v curl >/dev/null 2>&1 || {
    echo "未找到 curl，无法检查服务是否启动。" >&2
    exit 1
  }
  command -v lsof >/dev/null 2>&1 || {
    echo "未找到 lsof，无法安全检查端口。" >&2
    exit 1
  }

  python="$(choose_python)"
  "$python" -c 'import uvicorn, fastapi' >/dev/null 2>&1 || {
    echo "Python 环境缺少后端依赖: $python" >&2
    echo "请激活 rag-src 环境，或设置 BACKEND_PYTHON。" >&2
    exit 1
  }

  # 检查两个端口后再启动，避免只启动一半。
  if ! service_running backend "$BACKEND_PID_FILE"; then
    ensure_port_free "$BACKEND_PORT"
  fi
  if ! service_running frontend "$FRONTEND_PID_FILE"; then
    ensure_port_free "$FRONTEND_PORT"
  fi

  if service_running backend "$BACKEND_PID_FILE"; then
    echo "后端已运行 (PID: $(read_pid "$BACKEND_PID_FILE"))"
  else
    (
      cd "$BACKEND_DIR"
      nohup "$python" -m uvicorn app:app --reload --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
      echo $! >"$BACKEND_PID_FILE"
    )
    if ! wait_for_url "http://127.0.0.1:$BACKEND_PORT/api/v1/health"; then
      echo "后端启动失败，日志末尾：" >&2
      tail -n 30 "$BACKEND_LOG" >&2
      stop_service backend "$BACKEND_PID_FILE"
      exit 1
    fi
    echo "后端已启动 (PID: $(read_pid "$BACKEND_PID_FILE"))"
  fi

  if service_running frontend "$FRONTEND_PID_FILE"; then
    echo "前端已运行 (PID: $(read_pid "$FRONTEND_PID_FILE"))"
  else
    (
      cd "$FRONTEND_DIR"
      nohup node "$FRONTEND_DIR/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort >"$FRONTEND_LOG" 2>&1 &
      echo $! >"$FRONTEND_PID_FILE"
    )
    if ! wait_for_url "http://127.0.0.1:$FRONTEND_PORT/"; then
      echo "前端启动失败，日志末尾：" >&2
      tail -n 30 "$FRONTEND_LOG" >&2
      stop_service frontend "$FRONTEND_PID_FILE"
      exit 1
    fi
    echo "前端已启动 (PID: $(read_pid "$FRONTEND_PID_FILE"))"
  fi

  echo ""
  echo "前端: http://127.0.0.1:$FRONTEND_PORT"
  echo "后端: http://127.0.0.1:$BACKEND_PORT"
  echo "API 文档: http://127.0.0.1:$BACKEND_PORT/docs"
  echo "日志: $BACKEND_LOG 和 $FRONTEND_LOG"
}

show_status() {
  local service pid_file port
  for service in backend frontend; do
    if [[ "$service" == backend ]]; then
      pid_file="$BACKEND_PID_FILE"
      port="$BACKEND_PORT"
    else
      pid_file="$FRONTEND_PID_FILE"
      port="$FRONTEND_PORT"
    fi
    if service_running "$service" "$pid_file"; then
      echo "$service 运行中 (PID: $(read_pid "$pid_file"), 端口: $port)"
    elif port_is_busy "$port"; then
      echo "$service 端口 $port 被其他进程占用"
    else
      echo "$service 未运行"
    fi
  done
}

case "${1:-restart}" in
  start)
    start_services
    ;;
  stop)
    stop_service frontend "$FRONTEND_PID_FILE"
    stop_service backend "$BACKEND_PID_FILE"
    ;;
  restart)
    stop_service frontend "$FRONTEND_PID_FILE"
    stop_service backend "$BACKEND_PID_FILE"
    start_services
    ;;
  status)
    show_status
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
