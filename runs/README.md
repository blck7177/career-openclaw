# runs/ directory

每次 discovery run 在此创建一个目录：`runs/YYYY-MM-DD_HHMMSS/`

## 目录结构

```
runs/2026-06-07_230000/
  run_config.yaml              ← profile + mode + budget 配置
  search_plan.md               ← agent 在 session 开始时写的搜索计划
  search_ledger.jsonl          ← 每次 query 的完整记录
  fetched_pages.jsonl          ← agent 实际 fetch 过的页面
  candidate_pool.jsonl         ← triaged 后的候选岗位（search phase 产出）
  skipped_results.jsonl        ← 跳过的结果和原因
  coverage_report.md           ← agent 对 coverage 的自我评估（session 结束必须写）
  query_expansion_log.jsonl    ← 每次 query expansion 的 reason
  jobs_structured.json         ← processing phase 产出（本次 run 所有结构化结果）
  run_summary.md               ← human-readable run summary
  run_log.jsonl                ← step-by-step 执行日志
  validation_errors.jsonl      ← 验证失败的记录
  raw_jds/                     ← 原始 JD 文本（gitignored）
    <job_id>.txt
```

## 命名规范
- `session_id` = `run_id` = `YYYY-MM-DD_HHMMSS` 时间戳（UTC）
- search phase 和 processing phase 共享同一个目录
