# Discovery Run — I/O Contract

```
Worker owns lifecycle, session, persistence, and ingestion gate.
Agent owns discovery strategy inside the run budget.
Service owns canonical database.
```

## 输入：读 task spec 文件

平台在你的 prompt 里给一个 task spec 文件路径。用 read tool 读它：

```json
{
  "session_id": "2026-06-16_145156",
  "workspace_id": "dev_default",
  "search_request": {
    "raw_user_request": "找 market risk / valuation control 相关岗位",
    "profile_name": "market_risk_nyc",
    "profile_summary": "...",
    "target_workstreams": ["market_risk_nyc", "structured_credit"]
  },
  "catalog_context": {
    "existing_job_count": 12,
    "recent_companies": ["Goldman Sachs", "JPMorgan"],
    "coverage_gaps": ["buy-side risk", "Ashby-board companies"]
  },
  "source_context": {
    "company_boards_path": "configs/company_boards.yaml",
    "source_policy_path": "configs/source_policy.yaml"
  },
  "budget": {
    "max_queries": 30,
    "max_pages": 40,
    "max_board_syncs": 10
  },
  "expected_output_paths": {
    "coverage_report": ".../runs/<session_id>/coverage_report.md",
    "discovery_notes": ".../runs/<session_id>/discovery_notes.md"
  }
}
```

后续所有 wrapper 调用都必须同时带上 `--session-id <session_id>` **和** `--workspace-id <workspace_id>`。

## 平台在你之前已做完的事

- `start_session` 已创建 run 目录 + `run_config.yaml`（含 `search_budget`）。
- **session 已存在**——你只需 `career_search_status` 确认，**绝不** `career_search_session start`。
- `catalog_context` 里的信息已由平台注入：你无需重新查询 job database。

## 你负责产出的内容

**必须产出：**
- `coverage_report.md`（写到 spec 的 `expected_output_paths.coverage_report` 路径）

**可选但鼓励：**
- `discovery_notes.md`（新发现的 source、策略观察、推荐下轮方向）
- `candidate_pool.jsonl` 增量由 `career_log_candidates` wrapper 自动写入，你不需要手写

## 平台在你之后会做的事（你不要碰）

1. **Discovery action 校验**：检查 run log 里是否有真实 discovery action（web_search / board_sync / classify_source）。无任何 discovery action → run 以 `SearchValidationError` 中止。有 action 但无候选 → valid no-yield run，正常进入 pipeline（空 pool）。
2. **`end_session`**：把你的 `coverage_report.md` 登记到 run 目录，置 `search_complete`。
3. **`run_processing_pipeline`**：`candidate_pool.jsonl` → fetch/extract/classify/validate → 结构化入库。
4. **Reflect turn**：驱动 `career-reflect-agent` 更新 strategy state。

## 硬性「不做」（I/O 层）

- 不 `career_search_session start` / `end`。
- 不写 `db/jobs.jsonl`、不写 final job report、不写 strategy_state.json。
- 不跑 processing pipeline。
- 不生成 Job Intelligence Report / Candidate Fit Report。
