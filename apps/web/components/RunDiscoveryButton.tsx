"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { triggerDiscovery, getAgentRun, type AgentRunTask } from "@/lib/api";

type Phase = "idle" | "form" | "submitting" | "polling" | "done" | "error";

function StatusPill({ status }: { status: AgentRunTask["status"] }) {
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

export default function RunDiscoveryButton() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [profileName, setProfileName] = useState("market_risk_nyc");
  const [searchBrief, setSearchBrief] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<AgentRunTask | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Operator token from env (injected at build time or left blank for DEV_MODE)
  const opToken = process.env.NEXT_PUBLIC_OPERATOR_TOKEN ?? "";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!searchBrief.trim()) return;
    setPhase("submitting");
    setError(null);
    try {
      const res = await triggerDiscovery(
        { profile_name: profileName, search_brief: searchBrief.trim() },
        opToken || undefined,
      );
      setTaskId(res.task_id);
      setPhase("polling");
      pollTask(res.task_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }

  function pollTask(id: string) {
    const interval = setInterval(async () => {
      try {
        const t = await getAgentRun(id, opToken || undefined);
        setTask(t);
        if (t.status === "completed" || t.status === "failed") {
          clearInterval(interval);
          setPhase("done");
        }
      } catch {
        // transient fetch error — keep polling
      }
    }, 5000);
  }

  if (phase === "idle") {
    return (
      <Button
        variant="default"
        size="sm"
        onClick={() => setPhase("form")}
        className="gap-1.5"
      >
        <span>+ Run Discovery</span>
      </Button>
    );
  }

  if (phase === "form") {
    return (
      <form
        onSubmit={handleSubmit}
        className="border rounded-lg p-4 space-y-3 bg-muted/30 max-w-lg"
      >
        <p className="text-sm font-medium">New Discovery Run</p>

        <div className="space-y-1">
          <Label htmlFor="profile" className="text-xs">Profile</Label>
          <Input
            id="profile"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            placeholder="market_risk_nyc"
            className="h-8 text-sm"
            required
          />
        </div>

        <div className="space-y-1">
          <Label htmlFor="brief" className="text-xs">Search Brief</Label>
          <Input
            id="brief"
            value={searchBrief}
            onChange={(e) => setSearchBrief(e.target.value)}
            placeholder="Find market risk analytics roles in NYC..."
            className="h-8 text-sm"
            required
          />
        </div>

        <div className="flex gap-2">
          <Button type="submit" size="sm">Start</Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setPhase("idle")}
          >
            Cancel
          </Button>
        </div>
      </form>
    );
  }

  if (phase === "submitting") {
    return (
      <div className="text-sm text-muted-foreground">Enqueuing discovery run…</div>
    );
  }

  if (phase === "polling" || phase === "done") {
    const result = task?.result;
    return (
      <div className="border rounded-lg p-4 max-w-lg space-y-2 bg-muted/30">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Discovery Run</p>
          {task && <StatusPill status={task.status} />}
        </div>
        <p className="text-xs text-muted-foreground font-mono">{taskId}</p>
        {task?.status === "running" && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Agent is searching… this takes several minutes.
          </p>
        )}
        {task?.status === "completed" && result && (
          <div className="text-xs space-y-0.5">
            <p>Queries run: <span className="font-medium">{result.queries_run ?? "—"}</span></p>
            <p>Candidates: <span className="font-medium">{result.candidates_captured ?? "—"}</span></p>
            <p>Jobs saved: <span className="font-medium">{result.jobs_saved ?? "—"}</span></p>
            {result.duration_seconds != null && (
              <p className="text-muted-foreground">{Math.round(result.duration_seconds)}s total</p>
            )}
          </div>
        )}
        {task?.status === "failed" && (
          <p className="text-xs text-rose-600 break-words">{task.error_message}</p>
        )}
        {phase === "done" && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-7"
            onClick={() => {
              setPhase("idle");
              setTask(null);
              setTaskId(null);
              setSearchBrief("");
            }}
          >
            Dismiss
          </Button>
        )}
      </div>
    );
  }

  // error
  return (
    <div className="border border-rose-200 rounded-lg p-3 max-w-lg">
      <p className="text-xs text-rose-600">{error}</p>
      <Button
        variant="ghost"
        size="sm"
        className="mt-2 text-xs h-7"
        onClick={() => setPhase("idle")}
      >
        Dismiss
      </Button>
    </div>
  );
}
