---
name: career-strategy-reviewer
description: "Post-run strategy review. Use after a run completes to analyze failures, coverage gaps, and update strategy state for the next run."
---

# Career Strategy Reviewer

## 角色
基于本轮 run 的结果，诊断 search 质量，更新 strategy_state，让下一轮更聪明。

## 使用前必读
1. `AGENTS.md` — 项目边界
2. `configs/workstream_taxonomy.yaml` — workstream 枚举

## 流程

### Step 1：读取本轮结果
```bash
# 读 run summary
cat runs/<session_id>/run_summary.md

# 读 coverage report
cat runs/<session_id>/coverage_report.md

# 如有 fetch failures，读取细节
cat runs/<session_id>/run_log.jsonl
```

### Step 2：诊断

分析以下几个维度：

**Fetch Failures**
- 哪些 URL 返回了 403/404？
- 是系统性失败（整个 source 被墙）还是偶发？
- 应该加入 `avoid_sources` 吗？

**Workstream Coverage**
- 哪些 workstream 有足够候选（sufficient）？
- 哪些 workstream 仍然 missing 或 weak？
- 下一轮应该优先补哪个方向？

**Query Effectiveness**
- 哪些 query pattern 产出了真实 JD URL？
- 哪些方向只返回 aggregator 页或搜索结果页？

### Step 3：写 strategy patch

基于诊断，写 patch 文件到 `agent_work/drafts/strategy_patch_<session_id>.json`：

```json
{
  "effective_sources": ["成功 fetch 的 source，例如：greenhouse.io 直链"],
  "avoid_sources": ["403/404 的 source，例如：swissre.com — HTTP 403"],
  "effective_query_patterns": ["产出真实 JD URL 的 query 模式"],
  "avoid_query_patterns": ["只返回搜索结果页的 query 模式"],
  "coverage_by_workstream": {
    "Market Risk / Exposure Monitoring": "sufficient",
    "Structured Credit / Credit Analytics": "missing"
  },
  "key_learnings": ["本轮新发现"],
  "recommended_next_searches": ["下一轮优先方向"]
}
```

### Step 4：写回 strategy state
```bash
./wrappers/career_update_strategy --run-id <session_id> --patch-file agent_work/drafts/strategy_patch_<session_id>.json
```

## 输出质量标准
- `avoid_sources` 必须说明 failure reason（403 / 404 / bot-blocked / login-required）
- `recommended_next_searches` 必须对应 missing workstream，不能是泛化建议
- 不要把 unknown 的 source 降权，只降有明确 failure evidence 的

## 禁止行为
- 不直接修改 db/strategy_state.json（必须通过 wrapper）
- 不修改 configs/（human-owned）
