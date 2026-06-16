# Coverage Draft Template（结束标志）

满足任一停止条件后，把 coverage draft 写到 spec 的 `expected_output_paths.coverage_draft` 路径。

## 关键差异（与 legacy 不同）

- 文件名是 **`coverage_draft.md`**（不是 `coverage_report.md`）。
- 写到 spec 给的 **run 目录路径**（不是 `agent_work/drafts/`）。
- **不要**调用 `career_search_session end`——平台的 `end_session` 会把这份 draft 提升为 run 目录下的 `coverage_report.md`。
- 写完即结束你的工作，不要再做别的。

## 固定格式（不要自由发挥 section 名）

```markdown
# Coverage Report — Session <session_id>

## Search Coverage
- Workstreams searched: <列出覆盖的 workstream>
- Source types used: <company_career_page / ats_board / aggregator 等>
- Company groups targeted: <尝试过的公司或公司类型>
- Queries run: N

## What Worked
<哪些 query / source 产出了真实 JD candidates？>

## What Failed
<哪些方向无结果？具体 failure mode：blocked_403 / no_results / fake_urls / search_result_pages_only>

## Coverage Gaps
<还缺哪些 workstream / company group 没有足够候选？>

## Candidates Summary
- Total candidates logged: N
- Relevant: N
- Maybe relevant: N
- Rejected (no URL / invalid): N

## Recommended Next Search Direction
<下一次 run 应该优先补充什么？>
```
