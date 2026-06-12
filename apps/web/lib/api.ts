/**
 * Typed API client for the Career OpenClaw FastAPI backend.
 *
 * All functions are async and throw on non-2xx responses.
 * Base URL defaults to http://localhost:8000 (override via NEXT_PUBLIC_API_URL).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Job {
  job_id: string;
  title: string;
  company: string;
  location: string;
  source_url: string;
  source_type: string;
  date_found: string;
  fetch_status: string;
  primary_workstream: string;
  secondary_workstreams: string[];
  classification_confidence: "high" | "medium" | "low";
  responsibilities: string[];
  required_skills: string[];
  preferred_skills: string[];
  tools_mentioned: string[];
  finance_domains: string[];
  seniority_inferred: string;
  likely_tasks: string[];
  likely_stakeholders: string[];
  inferred_team_context: string;
  run_id: string;
  possible_duplicate: boolean;
  validation_status: string;
}

export interface RunMeta {
  run_id: string;
  profile_name: string | null;
  mode: string | null;
  status: string | null;
  run_timestamp: string | null;
  search_completed_at: string | null;
  candidates_captured: number | null;
}

export interface RunDetail extends RunMeta {
  summary: {
    jobs_discovered?: number;
    jobs_fetched?: number;
    jobs_structured?: number;
    jobs_saved?: number;
    jobs_failed?: number;
    top_workstreams?: { workstream: string; count: number }[];
    duration_seconds?: number;
    fetch_failures?: unknown[];
  } | null;
  has_summary_md: boolean;
}

export interface JobReport {
  job_report_id: string;
  job_id: string;
  jd_hash: string;
  prompt_version: string;
  model: string | null;
  status: "active" | "superseded";
  created_at: string;
  narrative: string | null;
  structured: Record<string, unknown> | null;
  sources: unknown[] | null;
}

export interface AuthUser {
  workspace_id: string;
  user_id: string;
}

// ---------------------------------------------------------------------------
// Request helper
// ---------------------------------------------------------------------------

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw Object.assign(new Error(text), { status: res.status });
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function getMe(): Promise<AuthUser> {
  return req<AuthUser>("/auth/me");
}

export async function redeemInvite(code: string): Promise<AuthUser> {
  return req<AuthUser>("/auth/invite", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: "DELETE", credentials: "include" });
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export interface ListJobsParams {
  workstream?: string;
  company?: string;
  since?: string;
  limit?: number;
}

export async function listJobs(params: ListJobsParams = {}): Promise<Job[]> {
  const q = new URLSearchParams();
  if (params.workstream) q.set("workstream", params.workstream);
  if (params.company) q.set("company", params.company);
  if (params.since) q.set("since", params.since);
  if (params.limit) q.set("limit", String(params.limit));
  const qs = q.toString() ? `?${q}` : "";
  return req<Job[]>(`/api/jobs${qs}`);
}

export async function getJob(jobId: string): Promise<Job> {
  return req<Job>(`/api/jobs/${jobId}`);
}

export async function getJobReport(jobId: string): Promise<JobReport> {
  return req<JobReport>(`/api/jobs/${jobId}/job-report`);
}

export async function analyzeJob(jobId: string, force = false): Promise<{ task_id: string }> {
  return req<{ task_id: string }>(`/api/jobs/${jobId}/analyze?force=${force}`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export interface Task {
  task_id: string;
  workspace_id: string;
  task_type: string;
  status: TaskStatus;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function getTask(taskId: string): Promise<Task> {
  return req<Task>(`/api/tasks/${taskId}`);
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export async function listRuns(limit = 50): Promise<RunMeta[]> {
  return req<RunMeta[]>(`/api/runs?limit=${limit}`);
}

export async function getRun(runId: string): Promise<RunDetail> {
  return req<RunDetail>(`/api/runs/${runId}`);
}

export async function getRunSummaryMd(runId: string): Promise<string> {
  const res = await fetch(`${BASE}/api/runs/${runId}/summary`, { credentials: "include" });
  if (!res.ok) throw Object.assign(new Error("Not found"), { status: res.status });
  return res.text();
}
