"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  enqueueDiscoveryRun,
  getTask,
  type CandidateProfile,
  type DiscoveryRunResult,
  type SearchMode,
  type SearchDepth,
  type SearchParams,
} from "@/lib/api";
import Link from "next/link";
import { Loader2, Search, ChevronLeft, Target, Sliders, Compass } from "lucide-react";

interface StartDiscoveryButtonProps {
  profiles: CandidateProfile[];
}

type Phase =
  | "idle"
  | "mode-select"
  | "params-form"
  | "submitting"
  | "polling"
  | "done"
  | "error";

type SearchModeOption = "profile_based_exploration" | "directed_discovery" | "gap_fill_discovery";

interface SearchBuilderState {
  profileId: string;
  searchMode: SearchModeOption;
  location: string;
  remotePolicyValue: string;
  seniority: string;
  maxYearsExperience: string;
  workstreams: string;
  companyTypes: string;
  exclusions: string;
  targetNewJobs: string;
  searchDepth: SearchDepth;
  additionalInstruction: string;
}

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    running: "bg-blue-100 text-blue-800",
    completed: "bg-emerald-100 text-emerald-800",
    failed: "bg-rose-100 text-rose-800",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[status] ?? "bg-muted"}`}>
      {status}
    </span>
  );
}

function ObjectiveStatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const cfg: Record<string, { label: string; className: string }> = {
    met: { label: "Goal met", className: "bg-emerald-100 text-emerald-800" },
    partially_met: { label: "Partially met", className: "bg-yellow-100 text-yellow-800" },
    not_met: { label: "Goal not met", className: "bg-rose-100 text-rose-800" },
  };
  const c = cfg[status];
  if (!c) return null;
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${c.className}`}>
      {c.label}
    </span>
  );
}

const MODE_OPTIONS: Array<{
  id: SearchModeOption;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}> = [
  {
    id: "profile_based_exploration",
    icon: <Compass size={18} />,
    title: "Search from my profile",
    subtitle: "System infers search lanes from your background",
  },
  {
    id: "directed_discovery",
    icon: <Sliders size={18} />,
    title: "Search by criteria",
    subtitle: "You specify role, location, seniority, and more",
  },
  {
    id: "gap_fill_discovery",
    icon: <Target size={18} />,
    title: "Fill database gaps",
    subtitle: "Adds coverage in workstreams not yet catalogued",
  },
];

const DEPTH_OPTIONS: Array<{ id: SearchDepth; label: string; hint: string }> = [
  { id: "fast", label: "Fast", hint: "~20 queries" },
  { id: "balanced", label: "Balanced", hint: "~40 queries" },
  { id: "deep", label: "Deep", hint: "~80 queries" },
];

function splitCsv(s: string): string[] {
  return s.split(",").map((t) => t.trim()).filter(Boolean);
}

export default function StartDiscoveryButton({ profiles }: StartDiscoveryButtonProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [state, setState] = useState<SearchBuilderState>({
    profileId: profiles[0]?.candidate_profile_id ?? "",
    searchMode: "profile_based_exploration",
    location: "",
    remotePolicyValue: "flexible",
    seniority: "",
    maxYearsExperience: "",
    workstreams: "",
    companyTypes: "",
    exclusions: "",
    targetNewJobs: "10",
    searchDepth: "balanced",
    additionalInstruction: "",
  });

  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>("pending");
  const [attemptLabel, setAttemptLabel] = useState<string>("");
  const [result, setResult] = useState<DiscoveryRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof SearchBuilderState>(k: K, v: SearchBuilderState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!state.profileId) return;
    setPhase("submitting");
    setError(null);

    const searchParams: SearchParams = {};
    const locs = splitCsv(state.location);
    if (locs.length) searchParams.location = locs;
    if (state.remotePolicyValue !== "flexible")
      searchParams.remote_policy = state.remotePolicyValue as SearchParams["remote_policy"];
    const sen = splitCsv(state.seniority);
    if (sen.length) searchParams.seniority = sen;
    if (state.maxYearsExperience) {
      const n = parseInt(state.maxYearsExperience, 10);
      if (!isNaN(n)) searchParams.max_years_experience = n;
    }
    const ws = splitCsv(state.workstreams);
    if (ws.length) searchParams.workstreams = ws;
    const ct = splitCsv(state.companyTypes);
    if (ct.length) searchParams.company_types = ct;
    const ex = splitCsv(state.exclusions);
    if (ex.length) searchParams.exclusions = ex;

    const target = parseInt(state.targetNewJobs, 10);

    try {
      const res = await enqueueDiscoveryRun({
        profile_id: state.profileId,
        search_mode: state.searchMode as SearchMode,
        search_params: searchParams,
        target_new_jobs: isNaN(target) ? 10 : target,
        search_depth: state.searchDepth,
        additional_instruction: state.additionalInstruction.trim() || undefined,
      });
      setTaskId(res.task_id);
      setTaskStatus("pending");
      setAttemptLabel("Starting search…");
      setPhase("polling");
      pollTask(res.task_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }

  function pollTask(id: string) {
    let attemptShown = false;
    const interval = setInterval(async () => {
      try {
        const task = await getTask(id);
        setTaskStatus(task.status);

        // Show attempt hint while running
        if (task.status === "running" && !attemptShown) {
          setAttemptLabel("Attempt 1: searching sources…");
          attemptShown = true;
        }

        if (task.status === "completed" || task.status === "failed") {
          clearInterval(interval);
          if (task.status === "completed") {
            const r = task.result as DiscoveryRunResult | null;
            setResult(r);
            // Update label to show attempt count
            if (r?.attempts_run && r.attempts_run > 1) {
              setAttemptLabel(`Completed in ${r.attempts_run} attempts`);
            } else {
              setAttemptLabel("Completed");
            }
            router.refresh();
          } else {
            setError(task.error_message ?? "Discovery run failed");
          }
          setPhase("done");
        }
      } catch {
        // transient fetch error — keep polling
      }
    }, 5000);
  }

  function reset() {
    setPhase("idle");
    setResult(null);
    setTaskId(null);
    setError(null);
    setAttemptLabel("");
  }

  // --- idle ---
  if (phase === "idle") {
    return (
      <Button variant="default" size="sm" onClick={() => setPhase("mode-select")} className="gap-1.5">
        <Search size={14} />
        Start Discovery
      </Button>
    );
  }

  // --- mode selection ---
  if (phase === "mode-select") {
    return (
      <div className="border rounded-lg p-4 space-y-3 bg-muted/30 max-w-lg">
        <p className="text-sm font-medium">Choose search mode</p>
        {profiles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No profiles yet.{" "}
            <Link href="/profile/new" className="text-primary hover:underline">
              Create one first
            </Link>
            .
          </p>
        ) : (
          <>
            <div className="space-y-1">
              <Label htmlFor="profile-select-mode" className="text-xs">Candidate Profile</Label>
              <select
                id="profile-select-mode"
                value={state.profileId}
                onChange={(e) => set("profileId", e.target.value)}
                className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              >
                {profiles.map((p) => (
                  <option key={p.candidate_profile_id} value={p.candidate_profile_id}>
                    {p.display_name ?? p.candidate_profile_id}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2 pt-1">
              {MODE_OPTIONS.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => {
                    set("searchMode", m.id);
                    setPhase("params-form");
                  }}
                  className={`w-full flex items-start gap-3 text-left rounded-lg border px-3 py-2.5 text-sm transition-colors hover:bg-accent hover:border-primary/40 ${
                    state.searchMode === m.id ? "border-primary/60 bg-accent" : "border-input"
                  }`}
                >
                  <span className="mt-0.5 shrink-0 text-primary">{m.icon}</span>
                  <span>
                    <span className="font-medium block">{m.title}</span>
                    <span className="text-xs text-muted-foreground">{m.subtitle}</span>
                  </span>
                </button>
              ))}
            </div>

            <Button type="button" variant="ghost" size="sm" onClick={reset}>
              Cancel
            </Button>
          </>
        )}
      </div>
    );
  }

  // --- params form ---
  if (phase === "params-form") {
    const isDirected = state.searchMode === "directed_discovery";
    const modeLabel = MODE_OPTIONS.find((m) => m.id === state.searchMode)?.title ?? "Search";

    return (
      <form onSubmit={handleSubmit} className="border rounded-lg p-4 space-y-3 bg-muted/30 max-w-lg">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPhase("mode-select")}
            className="text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft size={15} />
          </button>
          <p className="text-sm font-medium">{modeLabel}</p>
        </div>

        {isDirected && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="location" className="text-xs">
                  Location <span className="text-muted-foreground font-normal">(comma-separated)</span>
                </Label>
                <input
                  id="location"
                  value={state.location}
                  onChange={(e) => set("location", e.target.value)}
                  placeholder="NYC, Jersey City"
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="seniority" className="text-xs">Seniority</Label>
                <input
                  id="seniority"
                  value={state.seniority}
                  onChange={(e) => set("seniority", e.target.value)}
                  placeholder="Analyst, Associate"
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="max-years" className="text-xs">Max years experience</Label>
                <input
                  id="max-years"
                  type="number"
                  min={0}
                  max={20}
                  value={state.maxYearsExperience}
                  onChange={(e) => set("maxYearsExperience", e.target.value)}
                  placeholder="3"
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="remote-policy" className="text-xs">Remote policy</Label>
                <select
                  id="remote-policy"
                  value={state.remotePolicyValue}
                  onChange={(e) => set("remotePolicyValue", e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                >
                  <option value="flexible">Flexible</option>
                  <option value="on-site">On-site</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="remote">Remote</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <Label htmlFor="workstreams" className="text-xs">
                Workstreams <span className="text-muted-foreground font-normal">(comma-separated)</span>
              </Label>
              <input
                id="workstreams"
                value={state.workstreams}
                onChange={(e) => set("workstreams", e.target.value)}
                placeholder="Market Risk, Valuation Control, Exposure Management"
                className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="company-types" className="text-xs">
                  Company types
                </Label>
                <input
                  id="company-types"
                  value={state.companyTypes}
                  onChange={(e) => set("companyTypes", e.target.value)}
                  placeholder="bank, asset_manager"
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="exclusions" className="text-xs">Exclude</Label>
                <input
                  id="exclusions"
                  value={state.exclusions}
                  onChange={(e) => set("exclusions", e.target.value)}
                  placeholder="model_validation, audit"
                  className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                />
              </div>
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label htmlFor="target-jobs" className="text-xs">Target new roles</Label>
            <input
              id="target-jobs"
              type="number"
              min={1}
              max={50}
              value={state.targetNewJobs}
              onChange={(e) => set("targetNewJobs", e.target.value)}
              className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Search depth</Label>
            <div className="flex gap-1 h-8">
              {DEPTH_OPTIONS.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => set("searchDepth", d.id)}
                  title={d.hint}
                  className={`flex-1 rounded-md border text-xs font-medium transition-colors ${
                    state.searchDepth === d.id
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-input bg-background hover:bg-accent"
                  }`}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="extra-instruction" className="text-xs">
            Additional instruction{" "}
            <span className="text-muted-foreground font-normal">(optional)</span>
          </Label>
          <textarea
            id="extra-instruction"
            value={state.additionalInstruction}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
              set("additionalInstruction", e.target.value)
            }
            placeholder={
              isDirected
                ? "e.g. Prefer direct company postings and mid-size firms."
                : "e.g. Focus on buy-side risk analytics roles."
            }
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 resize-none min-h-[60px]"
          />
        </div>

        <div className="flex gap-2">
          <Button type="submit" size="sm">
            <Search size={13} className="mr-1.5" />
            Start Search
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={reset}>
            Cancel
          </Button>
        </div>
      </form>
    );
  }

  // --- submitting ---
  if (phase === "submitting") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        Enqueuing discovery run…
      </div>
    );
  }

  // --- polling / done ---
  if (phase === "polling" || phase === "done") {
    const target = parseInt(state.targetNewJobs, 10) || 10;
    const r = result;

    return (
      <div className="border rounded-lg p-4 max-w-lg space-y-2 bg-muted/30">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Discovery Run</p>
          <div className="flex items-center gap-2">
            {r?.objective_status && <ObjectiveStatusBadge status={r.objective_status} />}
            <StatusPill status={taskStatus} />
          </div>
        </div>
        <p className="text-xs text-muted-foreground font-mono">{taskId}</p>

        {taskStatus === "running" && (
          <p className="text-xs text-muted-foreground animate-pulse flex items-center gap-1.5">
            <Loader2 size={12} className="animate-spin" />
            {attemptLabel || "Agent is searching…"}
          </p>
        )}
        {taskStatus === "pending" && (
          <p className="text-xs text-muted-foreground animate-pulse">Waiting for worker…</p>
        )}

        {taskStatus === "completed" && r && (
          <div className="text-xs space-y-1 pt-1">
            {/* Objective result summary */}
            <div className="rounded-md border bg-background p-2 space-y-0.5">
              <p className="font-medium text-xs mb-1">
                Target: {target} new roles
              </p>
              {r.new_jobs_inserted != null && (
                <p className="text-emerald-700 font-medium">
                  New roles inserted: {r.new_jobs_inserted}
                </p>
              )}
              {r.existing_jobs_updated != null && r.existing_jobs_updated > 0 && (
                <p>Existing updated: {r.existing_jobs_updated}</p>
              )}
              {r.possible_duplicates != null && r.possible_duplicates > 0 && (
                <p className="text-muted-foreground">
                  Already in catalog: {r.possible_duplicates}
                </p>
              )}
              {r.jobs_failed != null && r.jobs_failed > 0 && (
                <p className="text-muted-foreground">Fetch failures: {r.jobs_failed}</p>
              )}
            </div>

            {/* Per-attempt breakdown */}
            {r.attempt_summaries && r.attempt_summaries.length > 1 && (
              <div className="text-muted-foreground pt-0.5">
                {r.attempt_summaries.map((a) => (
                  <span key={a.attempt_number} className="mr-3">
                    Attempt {a.attempt_number}: {a.new_jobs_inserted} new
                  </span>
                ))}
              </div>
            )}

            {r.objective_reason && (
              <p className="text-muted-foreground italic">{r.objective_reason}</p>
            )}

            {r.queries_run != null && (
              <p className="text-muted-foreground">
                Queries: {r.queries_run} | Candidates: {r.candidates_captured ?? "—"} |{" "}
                {r.duration_seconds != null ? `${Math.round(r.duration_seconds)}s` : ""}
              </p>
            )}
          </div>
        )}

        {taskStatus === "failed" && error && (
          <p className="text-xs text-rose-600 break-words">{error}</p>
        )}

        {phase === "done" && (
          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={reset}>
            Dismiss
          </Button>
        )}
      </div>
    );
  }

  // --- error ---
  return (
    <div className="border border-rose-200 rounded-lg p-3 max-w-lg space-y-2">
      <p className="text-xs text-rose-600">{error}</p>
      <Button variant="ghost" size="sm" className="text-xs h-7" onClick={reset}>
        Dismiss
      </Button>
    </div>
  );
}
