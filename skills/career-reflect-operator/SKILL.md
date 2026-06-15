---
name: career-reflect-operator
description: "Bounded post-run reflection. Use when the platform asks you to reflect on an ALREADY-COMPLETED discovery run: diagnose failures/coverage, then write a strategy_patch.json + reflection_report.md. You do NOT write strategy_state.json, do NOT call career_update_strategy, do NOT run any pipeline."
---

# Career Reflect Operator

## 角色
你是一个 bounded reflection operator。对**平台已经跑完的一次 discovery run** 做复盘，
产出两个文件：一个机器可读的 `strategy_patch.json` 和一个人类可读的 `reflection_report.md`。
你**不**写 `strategy_state.json`、**不**调 `career_update_strategy`、**不**跑任何 pipeline、
**不**做 search。平台会校验你的 patch 并自己写回 strategy state。

```
Worker owns workflow + persistence.  Agent owns bounded reflection.  Service applies the patch.
```

## 使用前必读
1. `AGENTS.md` — 项目边界
2. `protocols/AGENT_IO_CONTRACT.md` — I/O 契约
3. `configs/workstream_taxonomy.yaml` — workstream 枚举（coverage 用合法 label）

## 输入
平台在消息里给你一个 task spec 文件路径，读它（不要靠记忆）：

```json
{
  "session_id": "2026-06-14_030203",
  "run_summary_path": ".../runs/<session_id>/run_summary.md",
  "coverage_report_path": ".../runs/<session_id>/coverage_report.md",
  "expected_output_paths": {
    "strategy_patch": ".../runs/<session_id>/strategy_patch.json",
    "reflection_report": ".../runs/<session_id>/reflection_report.md"
  }
}
```

## 流程

### Step 1：读取本轮结果
读 `run_summary_path` 和 `coverage_report_path`（用 read tool，不要用 exec 内联脚本）。
重点看：jobs saved / failed、fetch failures（哪些 URL 403/404）、各 workstream 覆盖。

### Step 2：诊断
- **Fetch Failures**：哪些 source 系统性失败（整源被墙）？应进 `avoid_sources` 吗？
- **Workstream Coverage**：哪些 sufficient / weak / missing？下一轮优先补哪个？
- **Query Effectiveness**：哪些 query pattern 产出真实 JD URL？哪些只返回 aggregator/搜索结果页？

### Step 3：写 strategy_patch.json（机器可读）
把 patch 写到 spec 的 `expected_output_paths.strategy_patch` 路径。**只允许以下字段**
（平台会拒绝未知字段）：

```json
{
  "effective_sources": ["成功 fetch 的 source 描述，含类型或域名"],
  "avoid_sources": ["<domain> — <failure_reason: 403 / 404 / bot-blocked / login-required>"],
  "effective_query_patterns": ["产出真实 JD URL 的 query 模式"],
  "avoid_query_patterns": ["只返回搜索结果页的 query 模式"],
  "coverage_by_workstream": { "<workstream_label from taxonomy>": "sufficient | weak | missing" },
  "key_learnings": ["本轮新发现"],
  "recommended_next_searches": ["下一轮优先方向，对应 missing workstream"]
}
```

list 字段会被平台 union 合并；`recommended_next_searches` 会被整体替换；
`coverage_by_workstream` 按 key 更新。空 patch（`{}`）也合法。

### Step 4：写 reflection_report.md（人类可读）
把简短复盘写到 spec 的 `expected_output_paths.reflection_report` 路径：本轮结论、
失败诊断、下一轮建议。写完即结束你的工作。

## 输出质量标准
- `avoid_sources` 必须说明 failure reason（403 / 404 / bot-blocked / login-required）
- `recommended_next_searches` 必须对应 missing workstream，不能是泛化建议
- 不要把 unknown 的 source 降权，只降有明确 failure evidence 的

## 禁止行为
- 不写 `strategy_state.json`、不调 `career_update_strategy`（平台负责落库）
- 不跑 processing pipeline、不做 search、不写 db/jobs
- 不修改 `configs/`、`src/`（human-owned）
- patch 里不得出现 Step 3 列表以外的字段

## 完成标志
`strategy_patch.json` 和 `reflection_report.md` 都已写到 spec 指定路径。
