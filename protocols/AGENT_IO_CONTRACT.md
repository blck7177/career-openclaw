# Agent I/O Contract

> 适用于经 `services/agent_gateway.py` 调用的 bounded agents：
> `career-search-agent` / `career-research` / `career-reflect-agent`。

## 核心边界

```
Worker owns workflow.
Agent owns bounded research/reflection action.
Service owns final artifact and persistence.
```

worker（及其 service）负责：task/session 生命周期、重试、超时、校验、pipeline 步序、
artifact 登记、报告生成、数据库写入。agent 只负责：bounded tool-use 推理、来源发现、
证据收集、run 后解释。**agent 不写最终系统状态（DB / MetadataStore / supersede）。**

## 调用契约（文件式交接）

1. **输入**：worker 通过 `AgentInvocation.input_spec` + `input_spec_path` 把结构化输入写到
   `agent_inputs/<key>.json`，agent 读它，而不是依赖超长 prompt。`prompt` 只用于告诉 agent
   读哪个 input 文件、执行哪个 skill、产出写到哪里。

2. **输出**：agent 把产物写到 `input_spec` 指定的 `expected_output_paths`（固定路径）。
   gateway 在每轮后检查这些路径是否落盘，全部存在即判 `complete`。

3. **Run log**：gateway 把每轮解析后的 agent JSON 输出 + 解析出的 `tool_calls` 落到
   `run_log_path`。`tool_calls`（真实 `web_search` / `web_fetch` 调用）是**反捏造校验的
   ground truth**——agent 不调用就不会出现在 log 里，无法伪造。

## `AgentInvocation` / `AgentRunResult`

- `AgentInvocation`：`agent_id`、`prompt`、`repo_root`、`expected_outputs`、
  `input_spec(+path)`、`run_log_path`、`turn_timeout_s`、`max_turns`、`wall_clock_s`。
- `AgentRunResult`：`status`（complete|incomplete|timeout）、`turns_used`、
  `outputs_present/outputs_missing`、`tool_calls`、`raw_outputs`、`raw_log_path`；
  便捷属性 `fetch_urls` / `web_fetch_count`。

## gateway 的边界（业务无关）

gateway **不知道** session / candidate / research bundle / 任何校验规则。它只负责：
写 input、驱动多轮（受 max_turns + wall_clock + 每轮 timeout 约束）、解析 tool_calls、
检查 expected_outputs、落 run log。所有业务判断（完成定义、provenance 校验、降级策略、
持久化）由调用方 service 完成。

## 每个 agent 的输入/输出（落地时补全）

| Agent | expected_outputs | 后续 fixed code |
|---|---|---|
| career-research | `research_notes.md`、`research_sources.json` | research_validator → analysis_service |
| career-search-agent | `coverage_report.md`（+ 增量 `candidate_pool.jsonl`） | provenance 校验（web_search tool_calls / queries_run）→ worker end_session → discovery pipeline |
| career-reflect-agent（Phase 3） | `strategy_patch.json`、`reflection_report.md` | worker validated applier |
