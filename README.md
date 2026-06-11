# Career OpenClaw Agent

> **把"我想找什么方向的工作"转化为"结构化岗位研究数据库"的 agent workflow。**

## 工作模式

一次完整 run 分三步：

```
Search  →  Process  →  Reflect
```

| 步骤 | 目标 | 由谁负责 |
|---|---|---|
| **Search** | 找到真实 JD URL，写入 candidate_pool | Agent-led，自由探索 |
| **Process** | 把 candidate_pool 批量处理成结构化 job records 入库 | Tool-enforced，deterministic |
| **Reflect** | 分析 failures 和 coverage gap，更新 strategy_state | Agent 诊断，写回策略 |

不是让 agent 变聪明，而是让流程有保证。

---

## 快速开始

### 1. 环境准备

```bash
cd career-openclaw
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 或 OPENAI_API_KEY
```

### 2. 配置 exec-approvals

将 `openclaw_integration/exec-approvals.template.json` 中的 allowlist 合并到 `~/.openclaw/exec-approvals.json`，让 OpenClaw 信任 wrappers 的 exec 调用。

### 3. 运行一次 discovery

在 OpenClaw 里触发 `career-research-orchestrator` skill，或手动执行三步：

**Step 1 — Search**
```bash
./wrappers/career_read_strategy                              # 加载上一轮策略
./wrappers/career_search_session start --profile market_risk_nyc
# agent: web_search → web_fetch → log-query → log_candidates（循环）
./wrappers/career_search_session end --session-id <id>
```

**Step 2 — Process**
```bash
./wrappers/career_run_discovery --from-candidates runs/<id>/candidate_pool.jsonl
./wrappers/career_validate_run --run-id <id>
./wrappers/career_summarize_run --run-id <id> --format markdown
```

**Step 3 — Reflect**
```bash
# agent 写 agent_work/drafts/strategy_patch_<id>.json
./wrappers/career_update_strategy --run-id <id> --patch-file agent_work/drafts/strategy_patch_<id>.json
```

**查询数据库**
```bash
./wrappers/career_query_jobs --format summary
./wrappers/career_query_jobs --workstream "Market Risk / Exposure Monitoring"
```

### 4. 自动驱动 Search 循环（可选）

```bash
bash scripts/monitor_search.sh <session_id>
```

---

## 项目结构

```
career-openclaw/
├── AGENTS.md                        ← OpenClaw 项目边界（agent 必须先读）
├── pyproject.toml                   ← Python 包定义 + 依赖
│
├── skills/                          ← OpenClaw skills（agent 工作模式）
│   ├── career-research-orchestrator/
│   │   └── SKILL.md                 ← 总控：Search → Process → Reflect 路由
│   ├── career-search-operator/
│   │   └── SKILL.md                 ← Search：agent-led 探索，高自由度
│   ├── career-run-processor/
│   │   └── SKILL.md                 ← Process：触发 pipeline，读结果
│   └── career-strategy-reviewer/
│       └── SKILL.md                 ← Reflect：诊断 failures，更新 strategy
│
├── protocols/                       ← 行为规范和领域知识（human-owned）
│   ├── PROJECT_PROTOCOL.md          ← pipeline 内部步骤规范
│   ├── SEARCH_STRATEGY_PROTOCOL.md  ← search session 详细指南
│   ├── OUTPUT_CONTRACT.md           ← 输出字段规范
│   ├── DATA_POLICY.md               ← source 和存储边界
│   └── WORKSTREAM_TAXONOMY.md       ← workstream 分类判断指南（枚举见 configs/workstream_taxonomy.yaml）
│
├── configs/                         ← human-owned 配置（agent 不可修改）
│   ├── search_profiles.yaml         ← 搜索 profile 定义
│   ├── source_policy.yaml           ← source 白名单/黑名单
│   └── workstream_taxonomy.yaml     ← workstream 枚举（机器可读，代码依赖）
│
├── schemas/                         ← JSON Schema 定义
│   ├── job_record.schema.json
│   ├── run_config.schema.json
│   └── run_summary.schema.json
│
├── src/career_intelligence/         ← Python 业务逻辑（agent 不直接调用）
│   ├── runner.py                    ← discovery pipeline 主入口
│   ├── fetcher.py                   ← web fetch + raw JD 存储
│   ├── extractor.py                 ← LLM 结构化提取
│   ├── classifier.py                ← workstream 分类
│   ├── validator.py                 ← schema 校验
│   ├── search_session.py            ← search session 状态管理
│   ├── strategy_state.py            ← 跨 run strategy 读写
│   ├── storage_jsonl.py             ← db 读写（去重 + append）
│   ├── run_logger.py                ← run artifact 记录
│   ├── researcher.py                ← LLM research helper
│   ├── llm_client.py                ← LLM API client
│   └── tools/                      ← CLI adapter（wrappers 的实际实现）
│
├── wrappers/                        ← agent 唯一合法执行入口（exec tool 调用）
│   ├── career_search_session        ← Search：session 生命周期
│   ├── career_log_candidates        ← Search：候选入池
│   ├── career_search_status         ← Search：查询 session 覆盖情况
│   ├── career_run_discovery         ← Process：candidate pool → db
│   ├── career_validate_run          ← Process：验证 run output
│   ├── career_query_jobs            ← Process/Query：查询已入库岗位
│   ├── career_summarize_run         ← Process/Reflect：run summary
│   ├── career_read_strategy         ← Reflect/Search：读取策略状态
│   └── career_update_strategy       ← Reflect：写回策略 patch
│
├── db/                              ← 持久化数据库（agent 不能直接写）
│   ├── jobs.jsonl                   ← 结构化岗位记录（append-only）
│   ├── job_index.json               ← URL hash 去重索引
│   ├── strategy_state.json          ← 跨 run 积累的搜索策略状态
│   └── schema.json
│
├── runs/                            ← 每次 run 的 artifacts（自动创建）
│   ├── README.md
│   └── <session_id>/
│       ├── run_config.yaml
│       ├── candidate_pool.jsonl     ← Search → Process 的边界文件
│       ├── search_ledger.jsonl      ← 每次 query 的审计记录
│       ├── coverage_report.md
│       ├── jobs_structured.json
│       ├── run_log.jsonl
│       ├── run_summary.json / .md
│       ├── validation_errors.jsonl  ← 出现时才有
│       ├── skipped_results.jsonl    ← 出现时才有
│       └── raw_jds/                 ← 每个成功 fetch 的 JD 原文
│           └── job_<hash>.txt
│
├── agent_work/                      ← agent 可写工作区
│   ├── drafts/                      ← query JSON、candidates batch、strategy_state.md、strategy_patch_*.json
│   ├── inputs/
│   └── outputs/
│
├── tests/
│   ├── fixtures/
│   ├── test_classifier.py
│   ├── test_dedupe.py
│   └── test_schema_validation.py
│
├── scripts/
│   └── monitor_search.sh            ← 自动驱动 Search loop 到完成的 bash 脚本
│
└── openclaw_integration/
    └── exec-approvals.template.json ← 需合并到 ~/.openclaw/exec-approvals.json
```

---

## OpenClaw 如何与本项目交互

```
OpenClaw agent
    │
    ├── read tool  ──→  protocols/*.md, configs/*.yaml, AGENTS.md, runs/*/run_summary.md
    ├── write tool ──→  agent_work/drafts/
    ├── exec tool  ──→  ./wrappers/* (唯一合法执行入口)
    │                      │
    │                      └──→  src/career_intelligence/ (Python pipeline)
    │                                  │
    │                                  └──→  db/jobs.jsonl (只能通过 runner 写入)
    │
    └── web_search / web_fetch  ──→  外部网站（Search 阶段）
```

**agent 的边界：**

| 可以 | 不可以 |
|---|---|
| 修改搜索策略、query 方向 | 修改 `configs/`、`src/`（human-owned）|
| 写 `agent_work/drafts/` | 直接写 `db/jobs.jsonl` |
| 调用任意 `./wrappers/*` | 调用 `src/` 下的模块 |
| 读任意文件 | 做简历优化、投递、outreach |

---

## 当前状态（2026-06-10）

- `db/jobs.jsonl` 已收录 **25 条**结构化岗位记录
- 已完成 **16 次** run，Search / Process / Reflect 三阶段全部模块稳定运行
- 已有 2 个搜索 profile：`market_risk_nyc`、`structured_credit_nyc`

**Workstream 覆盖情况：**

| Workstream | 状态 |
|---|---|
| Market Risk / Exposure Monitoring | sufficient |
| Valuation Control / IPV | sufficient |
| Risk Analytics / Automation / Data | 有记录 |
| Structured Credit / Credit Analytics | **missing — 下次优先** |
| Product Control / P&L Reporting | 未覆盖 |
| Model Risk / Model Validation | 未覆盖 |
| Stress Testing / Scenario Analysis | 未覆盖 |
| Treasury / ALM / Liquidity | 未覆盖 |

**有效 source（来自 strategy_state.json）：**
- `greenhouse.io` 直链（fetch 成功率高）
- `builtinnyc.com`
- `lever.co` job boards

**已知失效 source：**
- 大行 career page（GS、JPMorgan）— bot 保护 403
- `swissre.com` — HTTP 403
- `linkedin.com` aggregator 页 — 返回搜索结果页不是 JD 页
- `citi.com` job pages — 高 404 率

**Pipeline 性能参考：**

| 指标 | 数值 |
|---|---|
| Fetch 成功率 | ~50%（取决于目标网站 bot 保护） |
| 成功 fetch 后结构化入库率 | 100% |

---

## 核心设计原则

- **Search**: agent-led, ledger-constrained — 搜索策略给 agent，搜索状态强制记录
- **Process**: tool-enforced — fetch → classify → extract → validate → save 全部在 runner 内部
- **Reflect**: agent-driven — 诊断 failures，更新 strategy，让下一轮更聪明
- **边界**: `candidate_pool.jsonl` 是 Search / Process 的唯一边界，agent 不能直接写 `db/jobs.jsonl`
