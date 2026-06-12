# Role Dossier Protocol

## 目的

Role Dossier 是 job_record 的上层分析。

```
job_record     → "这个 JD 说了什么"（事实层）
role_dossier   → "这个岗位到底需要什么人、在解决什么问题"（理解层）
```

不要把 role dossier 的内容写回 job_record，也不要试图用 job_record 的字段替代 role dossier。两层分开存储。

---

## 触发时机

`career_analyze_roles` 是独立的 post-processing 步骤，**不自动接入主 pipeline**。

在以下情况下手动触发：
- 完成一轮 discovery run 后，需要深入理解某批岗位的能力要求
- 在 profile matching 之前，需要先建立岗位理解层

前提条件（以下都必须满足）：
1. 该 run 已跑过 `career_run_discovery`（`runs/<run_id>/jobs_structured.json` 存在）
2. 目标岗位的 `raw_jds/<job_id>.txt` 存在（fetch 成功）

---

## 触发方式

### 无 pre-research（基础模式）

```bash
# 分析该 run 全部已 fetch 的岗位
./wrappers/career_analyze_roles --run-id <run_id>

# 先查有哪些岗位可以分析
./wrappers/career_analyze_roles --run-id <run_id> --dry-run

# 先试跑前 5 个，看 report 质量
./wrappers/career_analyze_roles --run-id <run_id> --limit 5

# 只分析指定 job_id
./wrappers/career_analyze_roles --run-id <run_id> --job-ids <job_id1>,<job_id2>
```

### 带 pre-research（推荐，report 质量更高）

先由 `career_prepare_research` 生成 JD-guided 搜索计划，再由 agent 执行 web research，最后触发分析：

```bash
# Step 1：生成 targeted research plan（基于 job_record 字段派生 search queries）
./wrappers/career_prepare_research --run-id <run_id>

# Step 1a（可选）：先 dry-run 预览计划，不写文件
./wrappers/career_prepare_research --run-id <run_id> --dry-run

# Step 2：agent 读 role_research_tasks.jsonl，按 priority 做 web_search + web_fetch，
#          写 research_notes/<job_id>.md（见下方"Pre-Research 步骤"）

# Step 3：检查哪些 job 有 research notes
./wrappers/career_analyze_roles --run-id <run_id> \
  --research-notes-dir runs/<run_id>/research_notes \
  --dry-run

# Step 4：运行分析
./wrappers/career_analyze_roles --run-id <run_id> \
  --research-notes-dir runs/<run_id>/research_notes
```

`career_prepare_research` 跳过逻辑：已有 `research_notes/<job_id>.md` 的 job 自动跳过。加 `--force` 可强制重新生成计划。

`--research-notes-dir` 指定一个目录，wrapper 会在其中查找 `<job_id>.md` 文件。有 notes 的 job 会用 `[+research]` 标记。没有 notes 的 job 照常运行（向下兼容）。

---

## Pre-Research 步骤（agent 执行）

`career_prepare_research` 会在 `runs/<run_id>/` 写入：

```
role_research_plans/<job_id>.json   每个 job 的详细搜索计划（queries + context_gaps）
role_research_tasks.jsonl           所有 job 的搜索任务汇总（方便 agent 批量处理）
```

`role_research_tasks.jsonl` 每行一条任务，包含：`job_id`、`company`、`query`、`purpose`、`priority`（high/medium/low）、`research_notes_target`。

**搜索查询的派生逻辑（三层优先级）：**

| 优先级 | Query 来源 | 示例 |
|---|---|---|
| high | `company` + `division_or_business_line`（JD 明确写出的 org 名称） | `"Flex" "Risk Platform team"` |
| medium | `company` + `finance_domains` 中的前 3 个术语 | `"Flex" "credit risk" "fraud risk"` |
| low | `company` + title 关键词（去噪声词） | `"Flex" "risk" "engineering"` |

当 `division_or_business_line` 为空时，会用一次小 LLM call 从 `inferred_team_context` 中提取最有搜索价值的 org 名称，再生成 high priority query。

**Agent 按计划执行 web research（每个公司最多 3 次 web_search + web_fetch）：**

优先执行 high priority queries，其次 medium，low 作为 fallback。

**写 research notes 文件：**

文件路径：`runs/<run_id>/research_notes/<job_id>.md`

**格式（强制结构）：**

```markdown
# Research Notes — <company> (<job_id>)
Generated: <YYYY-MM-DD>

## Role-Specific Research Questions
(从 role_research_plans/<job_id>.json 的 context_gaps 复制，作为本次 research 的聚焦目标)
- <question 1>
- <question 2>

## Source Findings

### Source 1
- URL: <url>
- Source type: company_website | press_release | job_board | news | linkedin | other
- Relevant finding: <具体发现，只写 web_fetch 确认的内容>
- Related JD signal: <这条 finding 对应 JD 里的哪个词/职责/团队名称>
- What this helps interpret: <它帮助解释了什么>
- Evidence strength: high | medium | low
- Boundary: <它不能证明什么>

### Source 2
...（最多 3 条 source）

## Synthesis for Role Dossier
- What research clarifies about the JD: <具体说明>
- What research does NOT clarify: <具体说明>
- Remaining uncertainty: <还有哪些问题没搜到>
```

**格式规则：**
- 每条 finding 必须填写 `Related JD signal` 和 `What this helps interpret`，否则 Layer 1 LLM 无法有效融合 research 和 JD
- `Relevant finding` 只写从 web_fetch 确认的内容，不写推测（推测性内容留给 Layer 1 LLM 处理）
- 如果某家公司信息很少（刚融资的 startup、非知名公司），Source Findings 写 1 条，然后在 Synthesis 里如实说明 Research Gaps
- `Boundary` 字段必须填写——它防止 Layer 1 LLM 过度引申 research 内容
- 最多 3 条 source；宁可少而精，不要堆砌泛化的公司背景

---

## 输入

| 输入 | 路径 | 说明 |
|---|---|---|
| 已结构化 job records | `runs/<run_id>/jobs_structured.json` | 由 career_run_discovery 生成 |
| 原始 JD 文本 | `runs/<run_id>/raw_jds/<job_id>.txt` | 必须存在，fetch 失败的 job 跳过 |
| Workstream taxonomy | `configs/workstream_taxonomy.yaml` | 用于 Layer 2 分类约束 |
| Research notes（可选） | `runs/<run_id>/research_notes/<job_id>.md` | agent 预先写入，缺失时跳过，不报错 |

---

## 输出

| 输出 | 路径 | 说明 |
|---|---|---|
| Layer 1 报告 | `runs/<run_id>/role_dossier_reports/<job_id>.md` | 每个 job 一份 narrative report |
| Layer 2 结构 | `runs/<run_id>/role_dossiers.jsonl` | 所有 dossier 追加写入，event-log 模式 |

---

## 两层结构

### Layer 1：Narrative Role Report（推理层）

- 英文 markdown，7 个固定 section
- 目标：充分展开岗位理解，**不填 schema，不评估候选人**
- 允许推理、不确定性表达、多解释比较
- Evidence label 规范：`[JD]` / `[TITLE]` / `[COMPANY]` / `[RESEARCH]` / `[INFERENCE]`

固定 sections：
1. Business / Organizational Context
2. Position Function
3. Likely Daily Workflow
4. Underlying Capability Demands
5. Role Archetype / Family Classification
6. Evidence and Uncertainty Review
7. Analyst Summary

### Layer 2：Structured Role Dossier（存储层）

- 从 Layer 1 报告中 canonicalize，**不重新分析 JD**
- Schema 见 `schemas/role_dossier.schema.json`
- `primary_workstream` 必须是 `configs/workstream_taxonomy.yaml` 中的枚举 label，或 `"unknown"`
- 每个字段有 `evidence`（引用原文）和 `confidence`（high/medium/low）

---

## 分类约束

- `primary_workstream` / `secondary_workstreams` 的值**必须是 `workstream_taxonomy.yaml` 中的 label 字符串**，不得引入 taxonomy 之外的值
- 如果 JD 不属于任何 taxonomy workstream，填 `"unknown"`，并在 `uncertainty_notes` 说明原因

---

## 质量判断标准

读取 `runs/<run_id>/role_dossier_reports/<job_id>.md` 后，判断 Layer 1 report 质量：

**合格**：
- Section 4（Underlying Capability Demands）区分了 surface keyword 和 underlying capability
- 每个主要结论都有 evidence label（`[JD]` / `[INFERENCE]` 等）
- Uncertainty 写清楚了不确定的地方，而不是强行给出确定结论

**不合格（需要重新生成）**：
- Section 4 只是重复 JD keyword list
- 没有任何 evidence label
- Section 7（Analyst Summary）与 Section 1 内容几乎相同，没有新的综合结论

---

## 禁止行为

- 不评估任何候选人的匹配度
- 不写简历 bullet、cover letter、或 outreach 内容
- 不修改 job_record 已有字段（两层分开）
- 不直接写 `db/`（MVP 阶段 dossier 只写到 `runs/` 目录）
- 不对 fetch 失败的岗位强行生成 dossier
