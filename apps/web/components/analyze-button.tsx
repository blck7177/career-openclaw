"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { analyzeJob, getTask, type TaskStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Loader2, Sparkles, AlertCircle } from "lucide-react";

interface AnalyzeButtonProps {
  jobId: string;
}

type UIState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; taskId: string; status: TaskStatus }
  | { phase: "error"; message: string };

const POLL_INTERVAL_MS = 3000;

export function AnalyzeButton({ jobId }: AnalyzeButtonProps) {
  const router = useRouter();
  const [state, setState] = useState<UIState>({ phase: "idle" });

  const poll = useCallback(
    async (taskId: string) => {
      try {
        const task = await getTask(taskId);
        if (task.status === "completed") {
          router.push(`/jobs/${jobId}/report`);
          router.refresh();
          return;
        }
        if (task.status === "failed") {
          setState({
            phase: "error",
            message: task.error_message ?? "Analysis failed",
          });
          return;
        }
        setState({ phase: "polling", taskId, status: task.status });
      } catch {
        setState({ phase: "error", message: "Failed to poll task status" });
      }
    },
    [jobId, router]
  );

  useEffect(() => {
    if (state.phase !== "polling") return;
    const id = setInterval(() => poll(state.taskId), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [state, poll]);

  async function handleClick() {
    setState({ phase: "submitting" });
    try {
      const { task_id } = await analyzeJob(jobId);
      setState({ phase: "polling", taskId: task_id, status: "pending" });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start analysis";
      setState({ phase: "error", message: msg });
    }
  }

  function handleRetry() {
    setState({ phase: "idle" });
  }

  if (state.phase === "error") {
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 text-sm text-destructive">
          <AlertCircle size={14} />
          <span>{state.message}</span>
        </div>
        <Button size="sm" variant="outline" onClick={handleRetry}>
          Retry
        </Button>
      </div>
    );
  }

  if (state.phase === "polling") {
    const label =
      state.status === "running" ? "Analyzing…" : "Queued…";
    return (
      <Button size="sm" variant="outline" disabled>
        <Loader2 size={14} className="animate-spin mr-1.5" />
        {label}
      </Button>
    );
  }

  if (state.phase === "submitting") {
    return (
      <Button size="sm" variant="outline" disabled>
        <Loader2 size={14} className="animate-spin mr-1.5" />
        Starting…
      </Button>
    );
  }

  return (
    <Button size="sm" variant="outline" onClick={handleClick}>
      <Sparkles size={14} className="mr-1.5" />
      Analyze Role
    </Button>
  );
}
