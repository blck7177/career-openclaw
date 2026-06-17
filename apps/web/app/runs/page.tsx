import { listRuns, listProfiles, type RunMeta, type CandidateProfile } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Clock, CheckCircle2, XCircle, Circle } from "lucide-react";
import RunDiscoveryButton from "@/components/RunDiscoveryButton";
import StartDiscoveryButton from "@/components/StartDiscoveryButton";

export const dynamic = "force-dynamic";

function StatusIcon({ status }: { status: string | null }) {
  if (status === "search_complete" || status === "complete")
    return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed")
    return <XCircle size={14} className="text-rose-500" />;
  return <Circle size={14} className="text-muted-foreground" />;
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <Badge variant="outline" className="text-xs">—</Badge>;
  const color =
    status === "search_complete" || status === "complete"
      ? "bg-emerald-100 text-emerald-800"
      : status === "failed"
      ? "bg-rose-100 text-rose-800"
      : "bg-muted text-muted-foreground";
  return <Badge className={`${color} border-0 text-xs capitalize`}>{status.replace("_", " ")}</Badge>;
}

function fmtTs(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default async function RunsPage() {
  const [runs, profiles] = await Promise.all([
    listRuns(100).catch(() => [] as RunMeta[]),
    listProfiles().catch(() => [] as CandidateProfile[]),
  ]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Search Runs</h1>
          <p className="text-muted-foreground text-sm mt-1">{runs.length} run{runs.length !== 1 ? "s" : ""} total</p>
        </div>
        <div className="flex gap-2 items-start flex-wrap">
          <StartDiscoveryButton profiles={profiles} />
          <RunDiscoveryButton />
        </div>
      </div>

      {runs.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center">No runs found.</p>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <Link
              key={run.run_id}
              href={`/runs/${run.run_id}`}
              className="flex items-center justify-between border rounded-lg p-4 hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-center gap-3">
                <StatusIcon status={run.status} />
                <div>
                  <p className="text-sm font-medium font-mono">{run.run_id}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {run.profile_name ?? "unknown profile"} · {run.mode ?? "—"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-4 text-right">
                <div className="text-xs text-muted-foreground">
                  <p>{fmtTs(run.run_timestamp)}</p>
                  {run.candidates_captured != null && (
                    <p className="mt-0.5">{run.candidates_captured} jobs</p>
                  )}
                </div>
                <StatusBadge status={run.status} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
