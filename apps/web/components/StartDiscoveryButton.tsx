"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { enqueueDiscoveryRun, getTask, type CandidateProfile } from "@/lib/api";
import Link from "next/link";
import { Loader2, Search } from "lucide-react";

interface StartDiscoveryButtonProps {
  profiles: CandidateProfile[];
}

type Phase = "idle" | "form" | "submitting" | "polling" | "done" | "error";

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

export default function StartDiscoveryButton({ profiles }: StartDiscoveryButtonProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [profileId, setProfileId] = useState(profiles[0]?.candidate_profile_id ?? "");
  const [instruction, setInstruction] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>("pending");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!profileId) return;
    setPhase("submitting");
    setError(null);
    try {
      const res = await enqueueDiscoveryRun({
        profile_id: profileId,
        user_instruction: instruction.trim() || undefined,
        requested_mode: "auto",
      });
      setTaskId(res.task_id);
      setTaskStatus("pending");
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
        const task = await getTask(id);
        setTaskStatus(task.status);
        if (task.status === "completed" || task.status === "failed") {
          clearInterval(interval);
          if (task.status === "completed") {
            setResult(task.result as Record<string, unknown> | null);
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

  if (phase === "idle") {
    return (
      <Button variant="default" size="sm" onClick={() => setPhase("form")} className="gap-1.5">
        <Search size={14} />
        Start Discovery
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

        {profiles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No candidate profiles yet.{" "}
            <Link href="/profile/new" className="text-primary hover:underline">
              Create one first
            </Link>
            .
          </p>
        ) : (
          <>
            <div className="space-y-1">
              <Label htmlFor="profile-select" className="text-xs">Candidate Profile</Label>
              <select
                id="profile-select"
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                required
                className="w-full h-8 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              >
                {profiles.map((p) => (
                  <option key={p.candidate_profile_id} value={p.candidate_profile_id}>
                    {p.display_name ?? p.candidate_profile_id}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="instruction" className="text-xs">
                Direction{" "}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <textarea
                id="instruction"
                value={instruction}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInstruction(e.target.value)}
                placeholder="e.g. Focus on buy-side risk analytics roles at mid-size asset managers in NYC…"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 resize-none min-h-[72px]"
              />
              <p className="text-xs text-muted-foreground">
                Leave blank for profile-based exploration.
              </p>
            </div>

            <div className="flex gap-2">
              <Button type="submit" size="sm">
                <Search size={13} className="mr-1.5" />
                Start
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setPhase("idle")}>
                Cancel
              </Button>
            </div>
          </>
        )}

        {profiles.length === 0 && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setPhase("idle")}>
            Cancel
          </Button>
        )}
      </form>
    );
  }

  if (phase === "submitting") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        Enqueuing discovery run…
      </div>
    );
  }

  if (phase === "polling" || phase === "done") {
    return (
      <div className="border rounded-lg p-4 max-w-lg space-y-2 bg-muted/30">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Discovery Run</p>
          <StatusPill status={taskStatus} />
        </div>
        <p className="text-xs text-muted-foreground font-mono">{taskId}</p>

        {taskStatus === "running" && (
          <p className="text-xs text-muted-foreground animate-pulse flex items-center gap-1.5">
            <Loader2 size={12} className="animate-spin" />
            Agent is searching… this takes several minutes.
          </p>
        )}
        {taskStatus === "pending" && (
          <p className="text-xs text-muted-foreground animate-pulse">Waiting for worker…</p>
        )}

        {taskStatus === "completed" && result && (
          <div className="text-xs space-y-0.5">
            {result.queries_run != null && (
              <p>Queries run: <span className="font-medium">{String(result.queries_run)}</span></p>
            )}
            {result.candidates_captured != null && (
              <p>Candidates: <span className="font-medium">{String(result.candidates_captured)}</span></p>
            )}
            {result.jobs_saved != null && (
              <p>Jobs saved: <span className="font-medium">{String(result.jobs_saved)}</span></p>
            )}
            {result.duration_seconds != null && (
              <p className="text-muted-foreground">
                {Math.round(Number(result.duration_seconds))}s total
              </p>
            )}
          </div>
        )}

        {taskStatus === "failed" && error && (
          <p className="text-xs text-rose-600 break-words">{error}</p>
        )}

        {phase === "done" && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-7"
            onClick={() => {
              setPhase("idle");
              setResult(null);
              setTaskId(null);
              setInstruction("");
              setError(null);
            }}
          >
            Dismiss
          </Button>
        )}
      </div>
    );
  }

  // error phase
  return (
    <div className="border border-rose-200 rounded-lg p-3 max-w-lg space-y-2">
      <p className="text-xs text-rose-600">{error}</p>
      <Button
        variant="ghost"
        size="sm"
        className="text-xs h-7"
        onClick={() => setPhase("idle")}
      >
        Dismiss
      </Button>
    </div>
  );
}
