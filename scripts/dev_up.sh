#!/usr/bin/env bash
# dev_up.sh — one-command local dev stack (DEV MODE).
#
# Starts the full Career OpenClaw web stack in a single tmux session with three
# windows:
#   api    — FastAPI (DEV_MODE=1, port 8000)   so the X-Dev-Context bypass works
#   worker — task worker (sources .env first)   so LLM Analyze/Fit tasks succeed
#   web    — Next.js dev server (port 3000)      auto-sends X-Dev-Context: dev
#
# Usage:
#   scripts/dev_up.sh [up]      start the stack (default) and wait for /healthz
#   scripts/dev_up.sh attach    attach to the tmux session
#   scripts/dev_up.sh status    show window status
#   scripts/dev_up.sh down      stop the stack (kill the tmux session)
#
# After `up`, open http://localhost:3000 and attach with:
#   tmux attach -t career-dev      (detach again with Ctrl-b then d)

set -euo pipefail

SESSION="career-dev"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT=8000
WEB_PORT=3000

cd "$WORKSPACE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "ERROR: $*" >&2; exit 1; }

preflight() {
  command -v tmux >/dev/null 2>&1 || die "tmux not found (install: sudo apt install tmux)"
  [ -x ".venv/bin/uvicorn" ] || die "missing .venv/bin/uvicorn — create the venv and 'pip install -e .[dev,...]' first"
  [ -f ".env" ] || echo "WARN: no .env at repo root — Analyze Role / Fit Report tasks will fail (no LLM key)."
  [ -d "apps/web/node_modules" ] || echo "WARN: apps/web/node_modules missing — the web window will run 'npm install' first."
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_up() {
  preflight

  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' is already running. Use 'scripts/dev_up.sh attach' or 'down'."
    exit 0
  fi

  # Web window command: install deps on first run, then start the dev server.
  local web_cmd="npm run dev"
  if [ ! -d "apps/web/node_modules" ]; then
    web_cmd="npm install && npm run dev"
  fi

  echo "Starting tmux session '$SESSION'..."

  # Window 1: API (DEV_MODE=1 enables the X-Dev-Context auth bypass)
  tmux new-session -d -s "$SESSION" -n api -c "$WORKSPACE"
  tmux send-keys -t "$SESSION:api" \
    "DEV_MODE=1 .venv/bin/uvicorn apps.api.main:app --reload --port $API_PORT" C-m

  # Window 2: Worker (load .env so the LLM client finds its API key)
  tmux new-window -t "$SESSION" -n worker -c "$WORKSPACE"
  tmux send-keys -t "$SESSION:worker" \
    "set -a; [ -f .env ] && source .env; set +a; PYTHONPATH=. .venv/bin/python -m apps.worker.worker" C-m

  # Window 3: Web (Next.js dev server)
  tmux new-window -t "$SESSION" -n web -c "$WORKSPACE/apps/web"
  tmux send-keys -t "$SESSION:web" "$web_cmd" C-m

  # Wait for the API to answer /healthz.
  echo -n "Waiting for API on :$API_PORT "
  for _ in $(seq 1 30); do
    if curl -fs "http://localhost:$API_PORT/healthz" >/dev/null 2>&1; then
      echo " ok"
      break
    fi
    echo -n "."
    sleep 1
  done

  if curl -fs "http://localhost:$API_PORT/healthz" >/dev/null 2>&1; then
    local n
    n="$(curl -fs -H 'X-Dev-Context: dev' "http://localhost:$API_PORT/api/jobs" 2>/dev/null \
         | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo '?')"
    echo "API healthy — shared catalog has $n job(s) visible via dev context."
  else
    echo
    echo "API did not become healthy in time — check 'tmux attach -t $SESSION' (window: api)."
  fi

  cat <<EOF

Stack is up:
  Web : http://localhost:$WEB_PORT   (open this)
  API : http://localhost:$API_PORT

Attach to logs : tmux attach -t $SESSION   (switch windows: Ctrl-b then 0/1/2; detach: Ctrl-b then d)
Stop the stack : scripts/dev_up.sh down
EOF
}

cmd_down() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "Stopped session '$SESSION'."
  else
    echo "No session '$SESSION' running."
  fi
}

cmd_attach() {
  tmux has-session -t "$SESSION" 2>/dev/null || die "no session '$SESSION' — run 'scripts/dev_up.sh up' first"
  tmux attach -t "$SESSION"
}

cmd_status() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux list-windows -t "$SESSION"
  else
    echo "No session '$SESSION' running."
  fi
}

case "${1:-up}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  attach) cmd_attach ;;
  status) cmd_status ;;
  *)      die "unknown command '$1' (use: up | down | attach | status)" ;;
esac
