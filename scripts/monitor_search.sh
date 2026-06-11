#!/usr/bin/env bash
# monitor_search.sh — 持续驱动 career-intel agent 完成 search session
# 每轮结束后检查进度，直到 session status=search_complete 或 pipeline 跑完

set -euo pipefail

SESSION_ID="${1:-2026-06-10_054910}"
WORKSPACE="/home/ubuntu/career-openclaw"
LOG="$WORKSPACE/scripts/monitor_${SESSION_ID}.log"
MAX_TURNS=40
TURN=0

log() { echo "[$(date -u '+%H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== monitor_search.sh START session=$SESSION_ID ==="

send_turn() {
  local msg="$1"
  log "TURN $TURN → sending: ${msg:0:80}..."
  openclaw agent --agent career-intel --local --message "$msg" --json 2>&1 \
    | python3 -c "
import sys, json
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    text = d.get('result','') or d.get('message','') or raw[:300]
    # extract assistant text
    if isinstance(text, dict):
        for blk in text.get('content',[]):
            if blk.get('type')=='text':
                print(blk['text'][:400])
    else:
        print(str(text)[:400])
except:
    print(raw[:300])
" | tee -a "$LOG" || true
}

get_status() {
  cd "$WORKSPACE"
  ./wrappers/career_search_status --session-id "$SESSION_ID" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"queries={d['queries_run']}/30  candidates={d['candidates_captured']}  fetched={d['budget_used']['fetched_pages']}  remaining_q={d['budget_used']['queries_remaining']}\")
" 2>/dev/null || echo "status unavailable"
}

get_run_status() {
  python3 -c "
import yaml, sys
with open('$WORKSPACE/runs/$SESSION_ID/run_config.yaml') as f:
    d = yaml.safe_load(f)
print(d.get('status','unknown'))
" 2>/dev/null || echo "unknown"
}

# ── Main loop ─────────────────────────────────────────────
while [ $TURN -lt $MAX_TURNS ]; do
  TURN=$((TURN+1))
  STATUS=$(get_run_status)
  PROGRESS=$(get_status)
  log "Status=$STATUS  $PROGRESS"

  if [ "$STATUS" = "search_complete" ]; then
    log "Search phase complete. Triggering pipeline..."
    break
  fi

  # Extract queries_remaining
  REMAINING=$(cd "$WORKSPACE" && ./wrappers/career_search_status --session-id "$SESSION_ID" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['budget_used']['queries_remaining'])" 2>/dev/null || echo "0")

  if [ "$REMAINING" -le 0 ] 2>/dev/null; then
    log "Budget exhausted. Asking agent to end session..."
    send_turn "search budget 已用完（30 queries），请立即写 coverage_report.md 并调用 career_search_session end 结束 session。"
    sleep 10
    break
  fi

  # Continue search
  send_turn "继续搜索 risk analytics 岗位，session_id=${SESSION_ID}。还有 ${REMAINING} 个 query 额度。尽量多发现真实 JD URL 并 log candidates。如果已找到足够候选（≥20），写 coverage_report 并结束 session。"
  sleep 5
done

# ── Pipeline phase ────────────────────────────────────────
POOL="$WORKSPACE/runs/$SESSION_ID/candidate_pool.jsonl"
POOL_COUNT=0
[ -f "$POOL" ] && POOL_COUNT=$(wc -l < "$POOL")
log "Candidate pool size: $POOL_COUNT"

if [ "$POOL_COUNT" -gt 0 ]; then
  log "Running career_run_discovery..."
  cd "$WORKSPACE"
  ./wrappers/career_run_discovery --from-candidates "$POOL" 2>&1 | tee -a "$LOG"
  log "Pipeline done. Updating strategy..."
  send_turn "pipeline 已跑完，session_id=${SESSION_ID}，请调用 career_update_strategy 把本次 learnings 和有效 sources 写回 strategy_state.json。"
else
  log "WARNING: No candidates found. Skipping pipeline."
fi

log "=== monitor_search.sh DONE ==="
