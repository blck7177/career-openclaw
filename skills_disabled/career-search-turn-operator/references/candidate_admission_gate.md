# Candidate Admission Gate（最硬的操作规则）

这是本 skill 里**最不可妥协**的部分。平台用真实 tool-call 做反捏造校验，违反会导致候选被拒或整个 run 中止。

## web_search → web_fetch 是两步，不是一步

- `web_search` 是一个**工具名**（不是动词）。要搜索就调用 `web_search` 工具，它返回**搜索摘要 + URL 列表**。
- **绝不**用 `web_fetch` 去抓一个搜索引擎结果页（如 `google.com/search?q=...`、`bing.com/search?...`）来"搜索"——那不是真正的搜索，会得到一堆 listing/落地页候选，pipeline 抓不出 JD。**搜索一律用 `web_search` 工具。**
- 必须对每个候选 URL **单独调用 `web_fetch`** 确认真实 JD 内容，才能考虑入池。
- 不能只凭 search snippet 推断入池。

## 入池必要条件（全部满足才能 `career_log_candidates`）

1. URL 是**真实 job posting URL**：
   - **不是**搜索结果页（如 `google.com/search?q=...`、`linkedin.com/jobs/search?...`）。
   - **不是**公司主页 / about 页。
2. 已用 `web_fetch` 确认过该 URL 的真实内容。
3. 必填字段：`url`（非空真实 URL）、`title`、`company`。
4. 建议字段：`location`、`relevance`（`relevant` / `maybe`，默认 maybe）、`relevance_reason`、`workstream_hint`。

工具会硬拒以下两类候选（记入 `skipped_results.jsonl`）：
- 无真实 URL → `rejected_no_url`。
- URL 是搜索结果/listing 页（`google.com/search?...`、`*/jobs/search?...`、以 `/search` 结尾等）→ `rejected_search_page`。这类是"找工作的方式"，不是岗位本身，永远不能入池。

## 强制日志顺序（provenance）

```
web_search
  → career_search_session log-query   （记录 query + results；每次 search 必做）
  → web_fetch（逐个候选 URL 确认）
  → career_log_candidates             （确认的候选入池）
```

平台的两道闸门：

- **工具层**：`career_log_candidates` 在 `search_ledger` 为空（`queries_run=0`）时**拒绝全部候选**——必须先有真实 `web_search` + `log-query`。
- **Run 层**：worker 在「0 个真实 `web_search` 且 `queries_run=0`」时以 `SearchValidationError` **中止整个 run**。

所以：**永远先 `web_search` → `log-query`，再 `career_log_candidates`。** 记忆里的 / 印象中的 URL 不得入池。

## 工具机制（不是策略，是机制）

- **写文件用 write tool**（写 query JSON、candidates JSON、coverage draft）。
- **exec 只用于 `./wrappers/*`**（使用完整路径，如 `./wrappers/career_log_candidates`）。
- **绝不**用 `exec python3 -c "..."` 或 heredoc 内联脚本写文件 / 跑逻辑——exec allowlist 只允许 wrappers，内联脚本会被拒绝。

## log-query 与 log_candidates 调用形态

`log-query` 有两种形式，**优先用 inline（一个 exec 调用搞定，无需写临时文件）**：

```bash
# inline 形式（推荐）：记一条你真实搜过的 query
./wrappers/career_search_session log-query --session-id <id> \
  --query-text "<actual query string you searched>" \
  --source-type ats_board \
  --valid-url-count 2 --candidate-yield 1 --failure-mode none
```

只有当你要附带详细 `results_seen` 列表时才用 rich 形式（先 write JSON，再 exec）：

```json
// agent_work/drafts/query_01.json — 字段规范见 schemas/search_query.schema.json
{
  "query_text": "<actual query>",
  "search_intent": "<intent>",
  "query_type": "targeted_site_search",
  "query_family": "<from profile keywords>",
  "source_type": "company_career_page",
  "results_seen": [{"title": "...", "url": "...", "relevance": "relevant"}],
  "valid_url_count": 1,
  "candidate_yield": 1,
  "observed_failure_mode": "none"
}
```

```bash
./wrappers/career_search_session log-query --session-id <id> --query-file agent_work/drafts/query_01.json
```

字段以 `schemas/search_query.schema.json` 为准：`query_text` 必填（inline 别名 `query`），**写错/多余的字段会被拒绝并返回可读 error**（不会静默吞掉）。

`career_log_candidates`（单条或批量）：

```bash
./wrappers/career_log_candidates --session-id <id> \
  --url "<job posting url>" --title "<title>" --company "<company>" \
  --location "<loc>" --relevance relevant \
  --reason "<why it matches the profile>" --workstream-hint "<workstream>"
```

字段名是 `url`（标准名；`source_url` 也被接受）。
