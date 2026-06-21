# Tools Available to career-search-agent

## Built-in Tools

- `web_search(query)` — search the web
- `web_fetch(url)` — fetch a URL and return text content

## Approved Wrappers (via exec tool)

All wrappers are invoked via the exec tool using the **named form** (`name: <wrapper_name>`).
All wrappers accept `--task-spec <path> --output <path>`.

### career_search_status

Query current search session budget and coverage.

```
tool: exec
name: career_search_status
args:
  --task-spec <input.json 路径（来自 invocation message）>
  --output /tmp/status_result.json
```

### career_log_candidates

Write one or more triaged candidates to the candidate pool.

```
tool: exec
name: career_log_candidates
args:
  --task-spec /tmp/log_candidates_spec.json
  --output /tmp/log_candidates_result.json
```

### career_write_manifest

Write the final output manifest. Call once when done.

```
tool: exec
name: career_write_manifest
args:
  --task-spec /tmp/manifest_data.json
  --output <output_manifest_path（来自 invocation message）>
```

### career_fetch_source

Fetch and normalize a job posting from a specific ATS URL.

```
tool: exec
name: career_fetch_source
args:
  --task-spec /tmp/fetch_source_spec.json
  --output /tmp/fetch_result.json
```

## What NOT to Use

- Do not call wrappers by path (`~/career-openclaw/wrappers/...`) — use the named exec form above
- Do not use `python`, `python3`, `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use `curl`, `wget`, or any HTTP tool outside the approved wrappers
