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
    "profile_summary": "..."
  },
  "catalog_context": {
    "existing_job_count": 12,
    "recent_companies": ["Goldman Sachs", "JPMorgan"]
  },
  "strategy_context": {
    "coverage_gaps": ["buy-side risk", "Ashby-board companies"],
    "effective_sources": ["greenhouse.io/schonfeld", "lever.co/citadel"],
    "avoid_sources": ["linkedin.com — login-required", "glassdoor.com — bot-blocked"],
    "effective_query_patterns": ["site:greenhouse.io market risk New York"],
    "avoid_query_patterns": ["market risk jobs NYC — returns aggregator pages only"],
    "key_learnings": ["Schonfeld board_sync title filter too narrow; broaden to 'quant;risk;valuation'"],
    "recommended_next_searches": ["Retry Schonfeld with broader title_keywords", "Search Ashby-based buy-side firms"]
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

### `strategy_context` 字段说明

`strategy_context` 是跨 run 积累的策略经验，由每轮 reflect 后的 `apply_strategy_patch` 写入。**这是你避免重复失败的核心工具**——首轮 run 时各字段为空是正常的。

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `coverage_gaps` | 上轮 reflect 判定为 weak/missing 的 workstream | 优先把 budget 倾向这些方向 |
| `effective_sources` | 历史上成功 fetch 到 JD 的 source | 优先选用 board_sync 或 `site:` 搜索 |
| `avoid_sources` | 历史上系统性失败的 source（含 reason） | 跳过，不浪费 budget |
| `effective_query_patterns` | 产出过真实 JD URL 的 query 模式 | 参考用于 web_search |
| `avoid_query_patterns` | 只返回聚合器/搜索结果页的 query 模式 | 不重复使用 |
| `key_learnings` | 历史 run 的关键发现（最近 8 条） | 理解系统对这个搜索方向已知道什么 |
| `recommended_next_searches` | 上轮 reflect 推荐的下一步方向（最多 5 条） | 作为本轮起始策略参考，但你可以调整 |

## 平台在你之前已做完的事

- `start_session` 已创建 run 目录 + `run_config.yaml`（含 `search_budget`）。
- **session 已存在**——你只需 `career_search_status` 确认，**绝不** `career_search_session start`。
- `catalog_context` 和 `strategy_context` 里的信息已由平台注入：你无需重新查询 job database 或 strategy state。

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
