---
name: career-research-orchestrator
description: "End-to-end career job intelligence run. Use when the user asks to search for jobs, run a discovery session, build the job database, or do a full career research run."
---

# Career Research Orchestrator

## 角色
协调整个 job intelligence workflow。不执行细节，只负责按顺序调用正确的 sub-skill。

## 使用前必读
1. `AGENTS.md` — 项目边界和禁止行为

## Workflow

一次完整 run 分三步：

### 1. Search
**使用 `career-search-operator` skill**

目标：找到真实 JD URL，写入 candidate_pool，记录 search_ledger。

完成标志：`runs/<session_id>/candidate_pool.jsonl` 存在且不为空。

### 2. Process
**使用 `career-run-processor` skill**

目标：把 candidate_pool 批量处理成结构化 job records 并入库。

完成标志：`runs/<session_id>/run_summary.md` 存在，db/jobs.jsonl 已更新。

### 3. Reflect
**使用 `career-strategy-reviewer` skill**

目标：基于本轮 run_summary 和 failures，更新 strategy_state，供下一轮使用。

完成标志：`db/strategy_state.json` 已更新（last_updated 时间戳变化）。

**⚠ Reflect 是强制步骤，不是可选步骤。**
在以下情况下仍然必须执行：
- 本轮 saved = 0（failure mode 本身就是最重要的学习）
- run 只有 Search 没有 Process
- 用户没有明确要求 Reflect

**在 `db/strategy_state.json` 更新之前，不得向用户报告"run 完成"。**

## 禁止行为
- 不修改 `configs/`、`src/`（human-owned）
- 不直接写 `db/jobs.jsonl`
- 不做简历优化、投递、outreach
