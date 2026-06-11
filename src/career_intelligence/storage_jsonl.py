"""
JSONL Storage — event-log mode.

Design:
- jobs.jsonl: append-only event log (every write appends)
- job_index.json: maps url_hash → latest line number, job_id → latest line number
- Upsert: appends new record, updates index to point to latest line
- Dedup: same url_hash → upsert; same title+company+location but different URL → flag possible_duplicate
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]


def _dedup_key(record: dict[str, Any]) -> str:
    title = (record.get("title") or "").lower().strip()
    company = (record.get("company") or "").lower().strip()
    location = (record.get("location") or "").lower().strip()
    return f"{company}|{title}|{location}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index(db_dir: Path) -> dict[str, Any]:
    index_path = db_dir / "job_index.json"
    if not index_path.exists():
        return {"by_url_hash": {}, "by_job_id": {}, "by_dedup_key": {}, "total_jobs": 0, "last_updated": None}
    with open(index_path) as f:
        return json.load(f)


def _save_index(db_dir: Path, index: dict[str, Any]) -> None:
    index["last_updated"] = _now_iso()
    with open(db_dir / "job_index.json", "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for _ in f:
            count += 1
    return count


def upsert_job(record: dict[str, Any], db_dir: Path) -> dict[str, Any]:
    """
    Append a job record to jobs.jsonl and update job_index.json.
    Returns {"action": "inserted"|"updated", "job_id": ..., "line": ...}
    """
    db_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = db_dir / "jobs.jsonl"

    index = _load_index(db_dir)
    url = record.get("source_url", "")
    url_h = _url_hash(url) if url else ""
    dedup_k = _dedup_key(record)
    job_id = record.get("job_id", "")

    existing_url_entry = index["by_url_hash"].get(url_h)
    existing_dedup_entry = index.get("by_dedup_key", {}).get(dedup_k)

    action = "inserted"
    if existing_url_entry:
        action = "updated"
    elif existing_dedup_entry and existing_dedup_entry.get("url_hash") != url_h:
        record["possible_duplicate"] = True

    line_number = _count_lines(jobs_path)
    with open(jobs_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if url_h:
        index["by_url_hash"][url_h] = {"job_id": job_id, "line": line_number}
    if job_id:
        index["by_job_id"][job_id] = {"line": line_number, "url_hash": url_h}
    if "by_dedup_key" not in index:
        index["by_dedup_key"] = {}
    index["by_dedup_key"][dedup_k] = {"job_id": job_id, "url_hash": url_h}

    if action == "inserted":
        index["total_jobs"] = index.get("total_jobs", 0) + 1

    _save_index(db_dir, index)
    return {"action": action, "job_id": job_id, "line": line_number}


def query_jobs(
    db_dir: Path,
    workstream: str | None = None,
    company: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Query jobs.jsonl with optional filters.
    Returns the latest version of each job (by job_id, last occurrence wins).
    """
    jobs_path = db_dir / "jobs.jsonl"
    if not jobs_path.exists():
        return []

    latest: dict[str, dict] = {}
    with open(jobs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                job_id = record.get("job_id", "")
                latest[job_id] = record
            except json.JSONDecodeError:
                continue

    results = list(latest.values())

    if workstream:
        wl = workstream.lower()
        results = [r for r in results if wl in (r.get("primary_workstream") or "").lower()
                   or any(wl in s.lower() for s in (r.get("secondary_workstreams") or []))]

    if company:
        cl = company.lower()
        results = [r for r in results if cl in (r.get("company") or "").lower()]

    if since:
        results = [r for r in results if (r.get("date_found") or "") >= since]

    results.sort(key=lambda r: r.get("date_found") or "", reverse=True)
    return results[:limit]
