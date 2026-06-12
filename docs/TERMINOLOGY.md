# Career OpenClaw — Canonical Terminology

This document defines the authoritative names for all core data objects and
system concepts. Use these names consistently in code, schemas, API routes,
UI labels, agent instructions, and documentation.

---

## Data Objects

### Job Record

A structured representation of a single job posting, extracted from a raw JD.

- Stored in: `data/workspaces/<workspace_id>/db/jobs.jsonl`
- Global cache: `data/global/jobs_cache.jsonl`
- Schema: `schemas/job_record.schema.json`
- Identity key: `job_id` (e.g. `job_a1b2c3d4`)
- Contains: title, company, location, source URL, workstream classification,
  extracted skills, tools, finance domains, seniority signals

**Not user-specific.** The same job record can be referenced by multiple workspaces.

---

### Job Intelligence Report  (formerly: Role Dossier)

A deep analysis of a Job Record using the raw JD and optional web research.
Describes what the role actually does, what organizational problem it solves,
and what underlying capabilities it demands — independent of any specific candidate.

- Stored in: `data/global/job_report_artifacts/<job_report_id>/`
  - `report.md` — Layer 1 narrative
  - `structured.json` — Layer 2 canonical JSON
  - `sources.json` — web research queries and URLs used
- Global index: `data/global/job_reports.jsonl`
- Schema: `schemas/job_report.schema.json`
- Identity key: `job_report_id`
- Cache key: `(job_id, jd_hash, prompt_version)` — same combination → reuse existing report
- Status lifecycle: `active` → `superseded` (when JD content changes and a new report is generated)

**Global, not user-specific.** If two workspaces analyze the same JD with the same
prompt version, the report is generated once and shared.

---

### Candidate Fit Report  (new concept)

An analysis of how a specific candidate's profile and resume match a specific
Job Intelligence Report. Contains skill gap assessment, fit score, and resume
rewrite strategy.

- Stored in: `data/workspaces/<workspace_id>/db/fit_reports.jsonl`
- Artifact: `data/workspaces/<workspace_id>/reports/<fit_report_id>/`
- Schema: `schemas/fit_report.schema.json`
- Identity key: `fit_report_id`
- References: `job_id`, `job_report_id`, `candidate_profile_id`, `resume_version_id`

**Workspace-private.** Never shared across workspaces.

---

### Workspace

The top-level data isolation unit for a user or client. All user-generated
data belongs to exactly one workspace.

- Data root: `data/workspaces/<workspace_id>/`
- Metadata: `workspaces` table in `data/app.sqlite`
- Contains: runs, db (jobs/fit reports), uploads, profiles, strategy_state

---

### Run

A single execution of the Search → Process → Reflect pipeline, or any sub-phase.
Each run belongs to a workspace.

- Artifacts: `data/workspaces/<workspace_id>/runs/<run_id>/`
- Metadata: `runs` table in `data/app.sqlite`
- Types: `search`, `process`, `reflect`, `full`
- Boundary artifact: `candidate_pool.jsonl` (handoff between Search and Process)

---

### Task

An async unit of work dispatched to the worker process. Created by the API,
consumed by the worker.

- Metadata: `task_queue` table in `data/app.sqlite`
- Types: `job_report`, `fit_report`, `search_run`, `process_run`
- Status lifecycle: `pending` → `running` → `completed` | `failed`

---

### Strategy State

Cross-run search intelligence for a workspace: effective sources, avoid sources,
query patterns, coverage gaps, and recommended next searches. Accumulated across
runs within a workspace.

- Location: `data/workspaces/<workspace_id>/strategy_state.json`
- Written by: `career_update_strategy` wrapper (agent-triggered at end of Reflect)
- Read by: `career_read_strategy` wrapper (agent-triggered at start of Search)

**Workspace-scoped.** Each workspace accumulates its own search strategy
independently.

---

### Candidate Profile

A structured representation of a candidate's positioning, target roles, and
preferences — derived from their resume and questionnaire answers.

- Stored in: `data/workspaces/<workspace_id>/profiles/`
- Schema: `schemas/candidate_profile.schema.json`
- Referenced by: Fit Reports

**Workspace-private.**

---

### Resume Profile

A factual extraction from an uploaded resume: work experience, skills, tools,
domains, projects, seniority signals.

- Stored in: `data/workspaces/<workspace_id>/uploads/`
- Schema: `schemas/resume_profile.schema.json`

**Workspace-private.**

---

## System Concepts

### Workspace Paths

The class `WorkspacePaths` in `src/career_intelligence/app_state/workspace_paths.py`
is the single source of truth for all filesystem paths within a workspace.
No code outside `app_state/` or `services/` should construct workspace paths manually.

### Request Context (`ctx`)

A `RequestContext` dataclass (`src/career_intelligence/app_state/context.py`)
carrying `workspace_id`, `user_id`, and optional `session_id`. Passed as the
first argument to all service layer functions. Core analyzers (e.g.
`role_analyzer.py`) do **not** accept `ctx` — they remain pure functions.

### dev_default

The development workspace, used when running CLI tools or wrappers locally
without an HTTP session. Populated from the original `db/` and `runs/` data.

```python
DEV_CTX = RequestContext(workspace_id="dev_default", user_id="dev_user")
```

---

## Deprecated Terms

| Old term | Replacement |
|---|---|
| `role_dossier` | `job_report` (global) or `fit_report` (workspace) |
| `RoleDossier` | `JobReport` (struct) |
| `db/strategy_state.json` | `data/workspaces/<id>/strategy_state.json` |
| `db/jobs.jsonl` | `data/workspaces/<id>/db/jobs.jsonl` (workspace) or `data/global/jobs_cache.jsonl` (global) |
| `runs/<session_id>/` | `data/workspaces/<id>/runs/<run_id>/` |
