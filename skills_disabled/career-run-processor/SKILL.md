---
name: career-run-processor
description: "Job discovery pipeline processor. Use when a candidate_pool.jsonl exists and needs to be processed into structured job records."
---

# Career Run Processor

## 角色
触发 deterministic pipeline，把 candidate_pool 转成结构化 job records 并入库。
**不思考 processing 细节，只触发、读结果、处理失败。**

## 使用前必读
1. `AGENTS.md` — 项目边界
2. `protocols/OUTPUT_CONTRACT.md` — 输出字段规范

## 流程

### Step 1：运行 pipeline
```bash
./wrappers/career_run_discovery --from-candidates runs/<session_id>/candidate_pool.jsonl
```
Pipeline 内部自动执行：fetch JD → LLM 提取 → workstream 分类 → schema 校验 → append db。

### Step 2：验证
```bash
./wrappers/career_validate_run --run-id <session_id>
```
如果有 validation errors，读取 `runs/<session_id>/validation_errors.jsonl`，报告给用户。

### Step 3：读取 summary
```bash
./wrappers/career_summarize_run --run-id <session_id> --format markdown
```
查看：jobs discovered / fetched / structured / saved / failed。
**重点看 Fetch Failures 部分**：记录哪些 URL 返回 403/404，传递给 `career-strategy-reviewer`。

### Step 4：查询结果（可选）
```bash
./wrappers/career_query_jobs --format summary
./wrappers/career_query_jobs --workstream "Market Risk / Exposure Monitoring"
```

### Step 5：触发 Reflect（必须）

**每次 Process 完成后，必须立即触发 `career-strategy-reviewer` skill。**

不需要等用户提示，不需要判断是否"值得"——无论本轮 saved 0 还是 20，都必须执行 Reflect。
Reflect 失败（如 0 candidates）反而最有价值：它记录了 failure mode，防止下一轮重蹈覆辙。

完成条件：`db/strategy_state.json` 的 `last_updated` 时间戳已更新。

## 失败处理
- 单个 job fetch 失败不中断整个 run（pipeline 内部处理）
- validation 失败的 record 不入库，记录在 validation_errors.jsonl
- 如果 0 jobs saved，报告给用户并建议检查 candidate_pool 质量

## 禁止行为
- 不介入 pipeline 中间步骤（fetch/extract/classify 由 pipeline 自动完成）
- 不直接写 db/jobs.jsonl
