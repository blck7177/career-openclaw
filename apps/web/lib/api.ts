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

/**
 * Base auth headers for every API request.
 *
 * Development: adds X-Dev-Context so the FastAPI DEV_MODE bypass applies to
 * both browser (client) requests AND Next.js server-side (SSR/RSC) fetches,
 * without needing "next/headers" in this file.
 *
 * Keeping this file free of "next/headers" is critical: api.ts is imported by
 * Client Components (e.g. fit-button, analyze-button), and Turbopack rejects
 * server-only modules in client bundles — even inside dynamic imports.
 *
 * Production SSR: Server Components that need to forward the session cookie
 * should import { serverAuthHeaders } from "@/lib/server-auth" (a server-only
 * module) and pass the result as extraHeaders to the individual fetch calls.
 */
function authHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...(process.env.NODE_ENV === "development" ? { "X-Dev-Context": "dev" } : {}),
  };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers as Record<string, string> | undefined),
    },
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
  await fetch(`${BASE}/auth/logout`, {
    method: "DELETE",
    credentials: "include",
    headers: authHeaders(),
  });
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
  const res = await fetch(`${BASE}/api/runs/${runId}/summary`, {
    credentials: "include",
    headers: authHeaders(),
  });
  if (!res.ok) throw Object.assign(new Error("Not found"), { status: res.status });
  return res.text();
}

// ---------------------------------------------------------------------------
// Candidate Profiles
// ---------------------------------------------------------------------------

export interface RepresentativeProject {
  title?: string;
  description: string;
  skills_used: string[];
  quantified_impact?: string;
}

export interface CandidateProfile {
  candidate_profile_id: string;
  workspace_id: string;
  created_at: string;
  profile_version: string;
  display_name?: string;
  years_experience: number;
  current_background: string;
  domain_experience: string[];
  technical_skills: string[];
  analytical_methods: string[];
  finance_domains: string[];
  tools: string[];
  representative_projects: RepresentativeProject[];
  target_workstreams?: string[];
  target_roles?: string[];
  constraints?: string;
}

export type CreateProfileInput = Omit<CandidateProfile, "candidate_profile_id" | "workspace_id" | "created_at" | "profile_version">;

export async function createProfile(data: CreateProfileInput): Promise<CandidateProfile> {
  return req<CandidateProfile>("/api/profiles", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listProfiles(): Promise<CandidateProfile[]> {
  return req<CandidateProfile[]>("/api/profiles");
}

export async function getProfile(profileId: string): Promise<CandidateProfile> {
  return req<CandidateProfile>(`/api/profiles/${profileId}`);
}

// ---------------------------------------------------------------------------
// Fit Reports
// ---------------------------------------------------------------------------

export interface FitReport {
  fit_report_id: string;
  workspace_id: string;
  job_id: string;
  job_report_id: string;
  candidate_profile_id: string;
  analyzed_at: string;
  prompt_version: string;
  overall_match_score: number;
  match_summary: string;
  strong_matches: Array<{ demand: string; evidence: string }>;
  partial_matches: Array<{ demand: string; gap_description: string }>;
  gaps: Array<{ demand: string; gap_description: string; severity: string }>;
  risk_flags: string[];
  interview_talking_points: string[];
  resume_rewrite_strategy: {
    positioning: string;
    keywords_to_add: string[];
    bullets_to_reframe: unknown[];
    evidence_to_surface: string[];
  };
  recommended_next_action: string;
}

export interface FitReportSummary {
  fit_report_id: string;
  candidate_profile_id: string;
  job_report_id: string;
  created_at: string;
  overall_match_score: number | null;
}

export async function enqueueFitReport(
  jobId: string,
  profileId: string,
  force = false,
): Promise<{ task_id: string }> {
  return req<{ task_id: string }>(`/api/jobs/${jobId}/fit`, {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId, force }),
  });
}

export async function getFitReport(
  fitReportId: string,
): Promise<{ structured: FitReport; narrative_md: string }> {
  return req<{ structured: FitReport; narrative_md: string }>(
    `/api/fit-reports/${fitReportId}`,
  );
}

export async function listJobFitReports(jobId: string): Promise<FitReportSummary[]> {
  return req<FitReportSummary[]>(`/api/jobs/${jobId}/fit-reports`);
}

// ---------------------------------------------------------------------------
// Operator — agent runs (discovery)
// ---------------------------------------------------------------------------

export interface AgentRunRequest {
  profile_name: string;
  search_brief: string;
  mode?: "exploratory" | "refresh";
  max_queries?: number;
  max_pages?: number;
}

export interface AgentRunTask {
  task_id: string;
  workspace_id: string;
  task_type: string;
  status: "pending" | "running" | "completed" | "failed";
  payload: AgentRunRequest;
  result: {
    session_id?: string;
    queries_run?: number;
    candidates_captured?: number;
    jobs_saved?: number;
    jobs_failed?: number;
    duration_seconds?: number;
  } | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function triggerDiscovery(
  body: AgentRunRequest,
  operatorToken?: string,
): Promise<{ task_id: string; message: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (operatorToken) headers["X-Operator-Token"] = operatorToken;
  return req<{ task_id: string; message: string }>("/api/operator/agent-runs", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export async function getAgentRun(
  taskId: string,
  operatorToken?: string,
): Promise<AgentRunTask> {
  const headers: Record<string, string> = {};
  if (operatorToken) headers["X-Operator-Token"] = operatorToken;
  return req<AgentRunTask>(`/api/operator/agent-runs/${taskId}`, { headers });
}

// ---------------------------------------------------------------------------
// User-facing discovery runs
// ---------------------------------------------------------------------------

export interface DiscoveryRunRequest {
  profile_id: string;
  user_instruction?: string;
  requested_mode?: "auto" | "directed_discovery" | "profile_based_exploration" | "gap_fill_discovery";
  max_queries?: number;
  max_pages?: number;
}

export interface DiscoveryRunResponse {
  task_id: string;
  run_id: string;
  message: string;
  requested_mode: string;
}

export async function enqueueDiscoveryRun(
  body: DiscoveryRunRequest,
): Promise<DiscoveryRunResponse> {
  return req<DiscoveryRunResponse>("/api/discovery-runs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getDiscoveryRun(taskId: string): Promise<Task> {
  return req<Task>(`/api/discovery-runs/${taskId}`);
}
