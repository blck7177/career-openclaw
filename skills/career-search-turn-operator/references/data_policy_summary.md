# Data Policy — Search Summary

> 全局完整版见 `protocols/DATA_POLICY.md`。此处是 bounded search turn 的精炼边界。

## 允许的 source（公开，不登录）

- 公开公司 career page（直接 URL）。
- LinkedIn 公开搜索结果（不登录、不用 LinkedIn API）。
- Indeed / Glassdoor 公开页面。
- Google / Bing 搜索结果（仅作 discovery surface，见下）。
- 在 `configs/source_policy.yaml` 中启用的第三方 job search API。

## 禁止

- 不登录任何平台、不绕过 paywall、不用 headless browser 模拟登录。
- 不保存 PII（候选人信息、内部员工信息）。
- search 阶段**不直接写 `db/jobs.jsonl`**（候选只经 `career_log_candidates`；岗位入库由 worker pipeline 完成）。

## Budget & 证据

- 单次 session 上限取 spec 的 `max_queries` / `max_pages`（默认 30 queries / 40 fetched pages）。
- web_fetch 之间建议间隔约 1 秒。
- 每条候选必须保留真实 `source_url`（evidence preservation）。

## 一条最易错的规则

**搜索结果页可以是 discovery surface，但永远不是 candidate URL。**
从搜索结果页里提取具体 job posting URL → `web_fetch` 确认 → 才入池。
