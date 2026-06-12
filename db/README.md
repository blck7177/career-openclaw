# db/ — LEGACY (read-only)

This directory has been migrated to the workspace-scoped data layout.

**New location:** `data/workspaces/dev_default/db/`

- `jobs.jsonl` → `data/workspaces/dev_default/db/jobs.jsonl`
- `job_index.json` → `data/workspaces/dev_default/db/job_index.json`
- `strategy_state.json` → `data/workspaces/dev_default/strategy_state.json`

These files are kept here for reference only and will not be updated.
All new writes go through the workspace-scoped paths.
See `docs/TERMINOLOGY.md` for the new data layout.
