# Career OpenClaw

> **把"我想找什么方向的工作"转化为"结构化岗位情报数据库"的 agent workflow + web 平台。**

---

## 架构概览

系统分两层运作：

**Phase 1 — Agent Pipeline（稳定运行）**

```
Search  →  Process  →  Research Notes  →  Analyze Roles  →  Reflect
```

OpenClaw agent 驱动五步流程，产出结构化 Job Records 和 Job Intelligence Reports。

**Phase 2 — Web 平台（Sprint 0–3 完成）**

```
Next.js UI  →  FastAPI  →  Worker（异步分析）
```

浏览器端查看岗位、Runs、报告，支持一键触发异步 Job Intelligence Report 生成。

---

## 快速开始

### 环境准备

```bash
cd career-openclaw
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,anthropic]"   # 或 openai
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 或 OPENAI_API_KEY
```

---

### 模式一：Agent / CLI 流程（legacy / 手动调试）

> ⚠️ 这是 legacy monolith 路径，由 `career-intel` agent 手动驱动，**已退出生产**。
> 生产环境的 discovery（search → process → reflect）全部由 worker 编排、走 bounded agents
> （`career-search-agent` / `career-research` / `career-reflect-agent`），入口见「模式二 Web 平台」
> 或 `POST /api/operator/agent-runs`。本节仅用于本地手动跑数 / 调试。

配置 exec-approvals（让 OpenClaw 信任 wrappers）：

```bash
# 将 openclaw_integration/exec-approvals.template.json 合并到 ~/.openclaw/exec-approvals.json
```

手动执行以下 wrapper 序列（legacy skills 已移至 `skills_disabled/`，OpenClaw 不再加载，因此无法再通过 `career-research-orchestrator` skill 触发）：

**Step 1 — Search**
```bash
./wrappers/career_read_strategy
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

**Step 3 — Analyze Roles（Job Intelligence Report）**

岗位分析已收敛到产品化 worker 路径，不再使用独立 CLI。通过 API 触发 `job_report` 任务，
worker 调 `analysis_service.create_job_report()` → `role_analyzer.analyze_role()`：

```bash
# JD-only 报告
curl -XPOST .../api/jobs/<job_id>/analyze
# JD + web research 增强报告（worker 先经 career-research 产出并校验 research_bundle）
curl -XPOST '.../api/jobs/<job_id>/analyze?with_research=true'
```

结果写入 `data/global/job_report_artifacts/<job_report_id>/` 并登记到 MetadataStore。

**Step 4 — Reflect**
```bash
./wrappers/career_update_strategy --run-id <id> --patch-file agent_work/drafts/strategy_patch_<id>.json
```

**查询数据库**
```bash
./wrappers/career_query_jobs --format summary
./wrappers/career_query_jobs --workstream "Market Risk / Exposure Monitoring"
```

**自动驱动 Search 循环**
```bash
bash scripts/monitor_search.sh <session_id>
```

---

### 模式二：Web 平台（本地开发，3 个终端）

```bash
# 终端 1 — FastAPI（本地开发需显式开启 DEV_MODE 才能用 X-Dev-Context 跳过 auth）
cd career-openclaw
DEV_MODE=1 .venv/bin/uvicorn apps.api.main:app --reload --port 8000

# 终端 2 — Worker
cd career-openclaw
PYTHONPATH=. .venv/bin/python -m apps.worker.worker

# 终端 3 — Next.js
cd career-openclaw/apps/web
npm install && npm run dev
# → http://localhost:3000
```

无浏览器时用 `X-Dev-Context: dev` header 跳过 auth。该 bypass **默认关闭**（secure by default），
需显式设 `DEV_MODE=1` 且 `ENV` 非 `production` 才生效；生产部署即使误设 `DEV_MODE=1` 也会被强制禁用：

```bash
curl -H "X-Dev-Context: dev" http://localhost:8000/api/jobs
curl -X POST -H "X-Dev-Context: dev" http://localhost:8000/api/jobs/<job_id>/analyze
```

### 模式三：Docker（api + worker）

```bash
cd career-openclaw
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
# API → http://localhost:8000
# Next.js 仍在本地运行
```

---

## 项目结构

```
career-openclaw/
├── AGENTS.md                        ← OpenClaw 项目边界（agent 必须先读）
├── pyproject.toml                   ← Python 包定义 + 依赖
├── docs/
│   └── TERMINOLOGY.md               ← 核心概念定义（Job Record / Job Intelligence Report / Task 等）
│
├── apps/                            ← Phase 2 应用层
│   ├── api/                         ← FastAPI REST API
│   │   ├── main.py                  ← App 入口（uvicorn apps.api.main:app）
│   │   ├── deps.py                  ← Auth + RequestContext 注入
│   │   └── routes/                  ← auth, jobs, runs, reports, tasks
│   ├── worker/                      ← 异步任务 worker
│   │   ├── worker.py                ← poll 主循环（python -m apps.worker.worker）
│   │   └── handlers/job_report.py   ← job_report 任务处理
│   └── web/                         ← Next.js 16 前端
│       ├── app/                     ← App Router 页面
│       ├── components/              ← nav、analyze-button、shadcn/ui
│       └── lib/api.ts               ← 类型化 API client
│
├── src/career_intelligence/         ← Python 业务逻辑（agent 不直接调用）
│   ├── runner.py                    ← discovery pipeline 主入口
│   ├── fetcher.py                   ← web fetch + raw JD 存储
│   ├── extractor.py                 ← LLM 结构化提取
│   ├── classifier.py                ← workstream 分类
│   ├── validator.py                 ← schema 校验
│   ├── role_analyzer.py             ← Job Intelligence Report 生成（Layer 1 + Layer 2）
│   ├── app_state/                   ← RequestContext、MetadataStore（SQLite）、WorkspacePaths
│   ├── services/                    ← job / run / report / task / analysis service
│   └── tools/                       ← CLI adapter（wrappers 的实际实现）
│
├── skills/                          ← OpenClaw skills（生产 agent 工作模式）
│   ├── career-discovery-operator/SKILL.md     ← career-search-agent（生产 autonomous discovery）
│   ├── career-job-research-operator/SKILL.md  ← career-research（生产 bounded 研究）
│   └── career-reflect-operator/SKILL.md       ← career-reflect-agent（生产 bounded 复盘）
│
├── skills_disabled/                 ← 已退役 legacy skills（不在 skill root 下，OpenClaw 不加载）
│   ├── career-research-orchestrator/SKILL.md  ← career-intel（legacy 全流程编排）
│   ├── career-search-operator/SKILL.md        ← career-intel（legacy 搜索）
│   ├── career-run-processor/SKILL.md          ← career-intel（legacy 处理）
│   ├── career-strategy-reviewer/SKILL.md      ← career-intel（legacy 策略复盘）
│   └── career-search-turn-operator/SKILL.md   ← 早期 bounded 搜索尝试（已被 discovery-operator 取代）
│
├── protocols/                       ← 行为规范和领域知识（human-owned）
│   ├── PROJECT_PROTOCOL.md
│   ├── SEARCH_STRATEGY_PROTOCOL.md
│   ├── OUTPUT_CONTRACT.md
│   ├── DATA_POLICY.md
│   └── WORKSTREAM_TAXONOMY.md
│
├── configs/                         ← human-owned 配置（agent 不可修改）
│   ├── search_profiles.yaml
│   ├── source_policy.yaml
│   └── workstream_taxonomy.yaml
│
├── schemas/                         ← JSON Schema 定义
│   ├── job_record.schema.json
│   ├── job_report.schema.json       ← Job Intelligence Report（含 jd_hash / prompt_version / status）
│   ├── fit_report.schema.json
│   ├── task.schema.json
│   ├── run_config.schema.json
│   └── run_summary.schema.json
│
├── wrappers/                        ← agent 唯一合法执行入口
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
├── data/                            ← 运行时数据（gitignored）
│   ├── app.sqlite                   ← SQLite WAL（12 张表）
│   ├── global/                      ← 全局 job report artifacts
│   └── workspaces/dev_default/
│       ├── db/jobs.jsonl            ← 结构化岗位记录（append-only）
│       ├── strategy_state.json
│       └── runs/                    ← run artifacts
│
├── db/                              ← LEGACY（只读，已迁移至 data/workspaces/）
├── runs/                            ← LEGACY（只读，已迁移至 data/workspaces/）
│
├── agent_work/                      ← agent 可写工作区
│   ├── drafts/
│   ├── inputs/
│   └── outputs/
│
├── tests/                           ← 52 个测试
├── scripts/
│   └── monitor_search.sh
├── infra/
│   ├── docker-compose.yml           ← api + worker
│   ├── Dockerfile.api
│   └── Dockerfile.worker
└── openclaw_integration/
    └── exec-approvals.template.json
```

---

## Web 平台页面

| 路由 | 内容 |
|---|---|
| `/` | Dashboard — KPI 卡片、workstream coverage 柱状图、recent runs |
| `/jobs` | Job 列表 — workstream/company 过滤、confidence badge |
| `/jobs/[id]` | Job 详情 — skills、responsibilities、tasks、stakeholders、tools |
| `/jobs/[id]/report` | Job Intelligence Report — Layer 1 narrative + Layer 2 structured (Tabs) |
| `/runs` | Run 列表 — status、profile、timestamp、jobs count |
| `/runs/[id]` | Run 详情 — discovery stats + run config；有 summary.md 时含 Summary tab |
| `/auth` | Invite code 登录 |

---

## API 端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| POST | `/auth/invite` | 兑换 invite code，写 session cookie |
| GET | `/auth/me` | 当前用户/workspace |
| GET | `/api/jobs` | 列出岗位（workstream / company / since 过滤）|
| GET | `/api/jobs/{id}` | 岗位详情 |
| GET | `/api/jobs/{id}/job-report` | 当前 active Job Intelligence Report |
| POST | `/api/jobs/{id}/analyze` | 入队异步分析 → 202 + task_id |
| GET | `/api/tasks/{id}` | 查询任务状态 |
| GET | `/api/runs` | Run 列表 |
| GET | `/api/runs/{id}` | Run 详情 |
| GET | `/api/runs/{id}/summary` | Run summary markdown |

---

## OpenClaw Agent 交互边界

```
OpenClaw agent
    │
    ├── read tool  ──→  protocols/*.md, configs/*.yaml, AGENTS.md, data/workspaces/*/runs/*/run_summary.md
    ├── write tool ──→  agent_work/drafts/
    ├── exec tool  ──→  ./wrappers/* （唯一合法执行入口）
    │                      │
    │                      └──→  src/career_intelligence/ （Python pipeline）
    │                                  │
    │                                  └──→  data/workspaces/dev_default/db/jobs.jsonl
    │
    └── web_search / web_fetch  ──→  外部网站（Search 阶段）
```

| 可以 | 不可以 |
|---|---|
| 修改搜索策略、query 方向 | 修改 `configs/`、`src/`（human-owned）|
| 写 `agent_work/drafts/` | 直接写 `db/jobs.jsonl` |
| 调用任意 `./wrappers/*` | 调用 `src/` 下的模块 |
| 读任意文件 | 做简历优化、投递、outreach |

---

## 当前状态（2026-06-12）

- `data/workspaces/dev_default/db/jobs.jsonl` 已收录 **~50 条**结构化岗位记录
- 已完成 **16+ 次** run，五阶段 pipeline 全部模块稳定运行
- **Phase 2 Web 平台 Sprint 0–3 全部完成**，52/52 tests pass，0 lints
- Docker infra 已就绪（api + worker）

### Phase 2 完成情况

| Sprint | 内容 | 状态 |
|---|---|---|
| Sprint 0 | Terminology、Schema、RequestContext、MetadataStore（12 张表）、数据迁移 | ✅ 完成 |
| Sprint 1 | Service layer（job / run / report / task service）、FastAPI read/write 端点 | ✅ 完成 |
| Sprint 2 | Next.js 16 App Router UI（Dashboard、Jobs、Runs、Report viewer、Auth）| ✅ 完成 |
| Sprint 3 | Analysis service（缓存/supersede）、Worker（异步生成）、Analyze button、Docker infra | ✅ 完成 |
| Sprint 4+ | Candidate Fit Report、web 触发 search/process、生产 auth 加固 | 计划中 |

### Workstream 覆盖情况

| Workstream | 状态 |
|---|---|
| Market Risk / Exposure Monitoring | sufficient |
| Valuation Control / IPV | sufficient |
| Risk Analytics / Automation / Data | 有记录 |
| Structured Credit / Credit Analytics | 待补充 |
| Product Control / P&L Reporting | 未覆盖 |
| Model Risk / Model Validation | 未覆盖 |
| Stress Testing / Scenario Analysis | 未覆盖 |
| Treasury / ALM / Liquidity | 未覆盖 |

### 有效 source（来自 strategy_state）

- `greenhouse.io` 直链（fetch 成功率高）
- `builtinnyc.com`
- `lever.co` job boards

### 已知失效 source

- 大行 career page（GS、JPMorgan）— bot 保护 403
- `swissre.com` — HTTP 403
- `linkedin.com` aggregator 页 — 返回搜索结果页而非 JD 页
- `citi.com` job pages — 高 404 率

### Pipeline 性能参考

| 指标 | 数值 |
|---|---|
| Fetch 成功率 | ~50%（取决于目标网站 bot 保护）|
| 成功 fetch 后结构化入库率 | 100% |

---

## 核心设计原则

- **Search**: agent-led, ledger-constrained — 搜索策略给 agent，搜索状态强制记录
- **Process**: tool-enforced — fetch → classify → extract → validate → save 全部在 runner 内部
- **Reflect**: agent-driven — 诊断 failures，更新 strategy，让下一轮更聪明
- **Job Intelligence Report**: `(job_id, jd_hash, prompt_version)` 三键全局缓存，支持 supersede
- **边界**: `candidate_pool.jsonl` 是 Search / Process 的唯一边界，agent 不能直接写 `jobs.jsonl`
