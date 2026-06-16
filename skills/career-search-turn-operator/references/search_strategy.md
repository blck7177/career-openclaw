# Search Strategy (bounded turn)

> 这是 bounded search turn 的策略指南。它**有意省略** session 生命周期、`board_sync`、source routing、`career_search_session end` 等内容——那些属于 legacy 全流程（见 `protocols/SEARCH_STRATEGY_PROTOCOL.md`），**不**是 bounded turn 的一部分。

## 你拥有目标，不拥有步骤

你负责**达成搜索目标**——发现相关的真实岗位候选——而不仅仅是执行 query。

你的搜索计划是临时的。可以随时根据证据修改：搜索结果、fetch 到的页面、缺失的候选、不相关结果、重复结果、source 限制、新发现的术语。

## 持续区分三件事

- **action completion**：跑了一个 query、fetch 了一个页面。
- **objective progress**：发现了有用的真实岗位候选。
- **strategy failure**：动作在完成，但目标没有推进。

当 objective progress 弱时，**先怀疑自己的方法**（source 选择、query 措辞、结果判读、triage 标准），不要假设市场上没有相关岗位。

## 你可以自由改变

query family、source 策略、目标公司、术语、relevance 标准、探索深度。

## 你不可以改变

- 数据边界（见 `data_policy_summary.md`）。
- Logging 要求：**每次 `web_search` 之后必须 `career_search_session log-query`**（这是 `queries_run` provenance 计数的来源）。

## 每 5 个 query 自评一次（简短）

每 5 个 query 调一次 `career_search_status`，然后给自己回答（每条 1–2 句，不是给用户的汇报）：

1. 这 5 个 query 想找什么？
2. 搜了哪些方向 / source？
3. 找到几个真实 JD URL？入池几条？
4. 哪些 query 没效果？failure mode（`blocked_403` / `no_results` / `fake_urls` / `search_result_pages_only`）？
5. 还缺哪些 workstream / company group / source type？
6. 下一步：继续、扩展、还是换方向？为什么？
7. 接下来具体搜什么？

## 停止条件（任一满足）

1. 候选数量达到目标（通常 ≥20，或按 search_brief 给的更小目标）。
2. 主要 source families 已覆盖。
3. 连续 ≥3 次策略调整仍 0 新候选。
4. Budget 耗尽（spec 的 `max_queries` / `max_pages`，默认 30 / 40）。

满足后写 `coverage_draft.md`（见 `coverage_draft_template.md`）并 STOP。
