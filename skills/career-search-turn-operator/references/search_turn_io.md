# Search Turn — I/O Contract (bounded)

> Search-specific 摘要。全局契约见 `protocols/AGENT_IO_CONTRACT.md`，此处只保留 bounded search turn 需要的部分。

```
Worker owns workflow + session lifecycle.
Agent owns the bounded search action.
Service owns persistence.
```

## 输入：读 task spec 文件（不要靠记忆）

平台在你的 prompt 里给一个 task spec 文件路径。用 read tool 读它，字段：

```json
{
  "session_id": "2026-06-14_030203",
  "profile_name": "market_risk_nyc",
  "search_brief": "本次要发现的岗位方向",
  "max_queries": 30,
  "max_pages": 40,
  "expected_output_paths": {
    "coverage_draft": ".../runs/<session_id>/coverage_draft.md"
  }
}
```

后续所有 wrapper 调用都用这个 `--session-id <session_id>`。

## 平台在你之前已经做完的事

- `start_session` 已创建 run 目录 + `run_config.yaml`（含 `search_budget`）。
- **session 已存在**——你只需 `career_search_status` 确认，**绝不** `career_search_session start`。

## 你只做这一件事

`career_search_status` 确认 → 搜索循环（见 `candidate_admission_gate.md`）→ 写 `coverage_draft.md` 到 spec 路径 → STOP。

## 平台在你之后会做的事（你不要碰）

1. **Provenance 校验**：统计 run log 里真实 `web_search` tool calls + ledger 的 `queries_run`。两者皆 0 → 整个 run 以 `SearchValidationError` 中止（无候选无意义，不降级）。
2. **`end_session`**：把你的 `coverage_draft.md` 提升为 run 目录下的 `coverage_report.md`，并把 `run_config.yaml` 置 `search_complete`。
3. **`run_processing_pipeline`**：`candidate_pool.jsonl` → fetch/extract/classify/validate → 结构化入 db。

## 完成标志

- `coverage_draft.md` 已写到 spec 的 `expected_output_paths.coverage_draft` 路径（gateway 据此判 complete）。
- `candidate_pool.jsonl` 由循环中的 `career_log_candidates` 增量落盘，**不是**你手写的文件。

## 硬性「不做」

- 不 `career_search_session start` / 不 `career_search_session end`（session 生命周期归平台）。
- 不跑 processing pipeline、不写 `db/jobs`、不生成 run_summary。
- 不生成 Job Report / Fit Report、不调 role analysis。
- 不调 `career_update_strategy`；不 `career_sync_board` / `career_register_board` / `career_classify_source`（不在本 bounded turn 的工具范围内）。
- 不登录平台、不绕过 paywall。
