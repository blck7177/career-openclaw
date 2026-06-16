---
name: career-search-turn-operator
description: "Bounded job-discovery search turn. Use when the platform asks you to run search turns for an already-created session: web_search → web_fetch → log candidates. You do NOT create or end the session, do NOT process or save jobs, do NOT write reports."
---

# Career Search Turn Operator

你是一个 **bounded search operator**。在**平台已经创建好的一个 search session** 里执行搜索循环，产出 candidate evidence。你**不**创建/结束 session、**不**跑 processing pipeline、**不**写 db、**不**生成任何 report。

```
Worker owns workflow + session lifecycle.  Agent owns the bounded search action.  Service owns persistence.
```

## 这个 skill 是 self-contained 的

执行本任务**只需读下面 5 个 skill-local references**（一跳直达，全部只服务本 bounded turn）。不需要去读 `protocols/SEARCH_STRATEGY_PROTOCOL.md`（那是 legacy 全流程文档，含 session lifecycle / board_sync 等**不适用**本 turn 的内容）。

1. `skills/career-search-turn-operator/references/search_turn_io.md` — 输入 spec、产物路径、平台前后做什么、硬性「不做」
2. `skills/career-search-turn-operator/references/search_strategy.md` — 目标导向策略、每 5 query 自评、停止条件
3. `skills/career-search-turn-operator/references/candidate_admission_gate.md` — **最硬规则**：入池条件 + provenance + 工具机制
4. `skills/career-search-turn-operator/references/coverage_draft_template.md` — `coverage_draft.md` 固定格式与路径
5. `skills/career-search-turn-operator/references/data_policy_summary.md` — source / 存储 / budget 边界

`AGENTS.md`（项目边界）由平台自动注入；`protocols/AGENT_IO_CONTRACT.md` / `protocols/DATA_POLICY.md` 仍是全局背景文档，需要细节时可查，但本 turn 的全部要求已在上面 references 内。

## 流程（概览）

1. **读 task spec**（路径在 prompt 里）→ 拿到 `session_id` 和 `expected_output_paths.coverage_draft`。
2. **`career_search_status --session-id <id>`** 确认 session、读 budget。**绝不 `career_search_session start`。**
3. **搜索循环**（细则见 `candidate_admission_gate.md`）：
   `web_search` → `career_search_session log-query`（每次 search 必做）→ `web_fetch`（逐个候选确认）→ `career_log_candidates`（确认的入池）。
   每 5 query 看一次 `career_search_status` 自评（见 `search_strategy.md`）。
4. **写 `coverage_draft.md`** 到 spec 路径（格式见 `coverage_draft_template.md`），然后 **STOP**。

## 禁止行为（速查）

- 不 `career_search_session start` / `end`；不 `career_sync_board` / `career_register_board` / `career_classify_source`。
- 不跑 pipeline、不写 db、不写 report、不调 role analysis、不调 `career_update_strategy`。
- 不把搜索结果页 / 公司主页当 candidate URL；不登录 / 不绕过 paywall。
- 不用 `exec python3 -c` 或 heredoc 内联脚本——exec 只用于 `./wrappers/*`。

## 完成标志

`coverage_draft.md` 已写到 spec 指定路径，且 `candidate_pool` 里每个候选都来自真实 `web_search` + `web_fetch`（平台用 run log 的真实 tool-call 做反捏造校验）。
