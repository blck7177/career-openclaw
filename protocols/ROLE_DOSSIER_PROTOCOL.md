# Job Report Protocol（原 Role Dossier）

> 历史命名 `role_dossier` 已统一为 `job_report`。Layer 2 结构 schema 见 `schemas/job_report.schema.json`。
>
> ℹ️ **bounded agent 指引**：生产的 `career-research` 不依赖本文件全文，改读 self-contained skill 包
> `skills/career-job-research-operator/SKILL.md` + 其 `references/`（`research_io.md` /
> `research_notes_format.md` / `source_verification_gate.md` / `data_policy_summary.md`）。
> 本文件保留为 Job Report 两层结构、触发路径与质量标准的全局背景文档。

## 目的

Job Report 是 job_record 的上层分析。

```
job_record   → "这个 JD 说了什么"（事实层）
job_report   → "这个岗位到底需要什么人、在解决什么问题"（理解层）
```

不要把 job_report 的内容写回 job_record，也不要试图用 job_record 的字段替代 job_report。两层分开存储。

---

## 触发方式（产品化路径）

岗位分析已收敛到产品化 worker 路径，**不再使用独立 CLI（`career_analyze_roles` / `career_prepare_research` 已废弃）**。

```
POST /api/jobs/<job_id>/analyze                 → JD-only 报告
POST /api/jobs/<job_id>/analyze?with_research=true → JD + web research 增强报告
```

流程：

```
job_report task
  ↓
worker 解析 job_record + JD
  ↓
若 with_research：
    worker 调 research_service.ensure_research_bundle()
      → career-research 执行 web_search/web_fetch，写 research_notes + sources
      → research_validator 校验（反捏造闸门，见 RESEARCH 部分）
      → 校验 failed 时降级为 JD-only
  ↓
analysis_service.create_job_report(research_bundle=...)
  ↓
role_analyzer.analyze_role()      ← 仍是 direct LLM call，agent 不写最终报告
  ↓
MetadataStore 记录 report + research provenance
```

前提条件：
1. job_record 已存在（discovery pipeline 已入库）
2. 可解析到原始 JD 文本（`raw_jd_path` 或内联 `jd_text`）

---

## Research（agent 执行，可选增强）

当 `with_research=true` 时，由 `career-research` 围绕一个已知 job/company/team 做补充研究。
它不是找新岗位，而是研究：公司业务背景、team/division context、role 在组织中的位置、
product/business line、为什么这个岗位存在、能澄清 JD 歧义的来源。

**Agent 执行（每公司最多 3 次 web_search + web_fetch）：**
按 research_planner 派生的优先级（high → medium → low）执行，每次 web_fetch 后调
`career_research_session log-fetch` 写入 fetch ledger。

**Research Notes 文件（强制格式）：**

```markdown
# Research Notes — <company> (<job_id>)
Generated: <YYYY-MM-DD>

## Role-Specific Research Questions
(从 research plan 的 context_gaps 复制，作为本次 research 的聚焦目标)
- <question 1>

## Source Findings

### Source 1
- URL: <url>
- Source type: company_website | press_release | job_board | news | linkedin | other
- Relevant finding: <具体发现，只写 web_fetch 确认的内容>
- Related JD signal: <这条 finding 对应 JD 里的哪个词/职责/团队名称>
- What this helps interpret: <它帮助解释了什么>
- Evidence strength: high | medium | low
- Boundary: <它不能证明什么>

## Synthesis for Job Report
- What research clarifies about the JD: <具体说明>
- What research does NOT clarify: <具体说明>
- Remaining uncertainty: <还有哪些问题没搜到>
```

**格式规则：**
- 每条 finding 必须填 `Related JD signal` 和 `Boundary`，否则该来源在校验时被降级为 unverified。
- `Relevant finding` 只写从 web_fetch 确认的内容，不写推测（推测留给 Layer 1 LLM）。
- 最多 3 条 source；宁可少而精。

### 反捏造闸门（research_validator）

research-agent 没有联网就编 research_notes 是必须防的失败模式（对标 search 侧 `queries_run==0` 闸门）。
双层校验：

- **Layer A（主）**：gateway 从 agent run log 解析真实发生的 `web_fetch` 调用（agent 无法伪造）。
- **Layer B（辅）**：`career_research_session log-fetch` 写的 fetch ledger，run log 不暴露工具调用时兜底。

判定：零真实 fetch → `failed`；notes 非空但 sources 空 → `failed`；逐源用 url_hash 核对是否出现在真实
fetch 集合，全部对不上 → `failed`，部分 → `partial`，全部命中 → `passed`。
`failed` 时 worker **降级**为 JD-only report（不崩），`used_research=false`。

---

## 输出

| 输出 | 路径 | 说明 |
|---|---|---|
| Layer 1 报告 | `data/global/job_report_artifacts/<job_report_id>/report.md` | narrative report |
| Layer 2 结构 | `data/global/job_report_artifacts/<job_report_id>/structured.json` | 匹配 job_report.schema.json |
| Research sources | `job_reports.sources_path`（MetadataStore） | research provenance |

---

## 两层结构

### Layer 1：Narrative Job Intelligence Report（推理层）

- 英文 markdown，7 个固定 section
- 目标：充分展开岗位理解，**不填 schema，不评估候选人**
- Evidence label 规范：`[JD]` / `[TITLE]` / `[COMPANY]` / `[RESEARCH]` / `[INFERENCE]`

固定 sections：
1. Business / Organizational Context
2. Position Function
3. Likely Daily Workflow
4. Underlying Capability Demands
5. Role Archetype / Family Classification
6. Evidence and Uncertainty Review
7. Analyst Summary

### Layer 2：Structured Job Report（存储层）

- 从 Layer 1 报告中 canonicalize，**不重新分析 JD**
- Schema 见 `schemas/job_report.schema.json`
- `primary_workstream` 必须是 `configs/workstream_taxonomy.yaml` 中的枚举 label，或 `"unknown"`
- 每个字段有 `evidence`（引用原文）和 `confidence`（high/medium/low）

---

## 质量判断标准

**合格**：
- Section 4（Underlying Capability Demands）区分了 surface keyword 和 underlying capability
- 每个主要结论都有 evidence label
- Uncertainty 写清楚了不确定的地方

**不合格（需重新生成）**：
- Section 4 只是重复 JD keyword list
- 没有任何 evidence label
- Section 7 与 Section 1 几乎相同

---

## 禁止行为

- 不评估任何候选人的匹配度
- 不写简历 bullet、cover letter、或 outreach 内容
- 不修改 job_record 已有字段（两层分开）
- agent 不写最终报告、不写 MetadataStore（agent 只产 research evidence）
