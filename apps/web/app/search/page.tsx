import { listRuns, listProfiles, type RunMeta, type CandidateProfile } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Search, Clock, ArrowRight, UserCircle } from "lucide-react";
import StartDiscoveryButton from "@/components/StartDiscoveryButton";

export const dynamic = "force-dynamic";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadge(status: string | null) {
  const map: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-800",
    running: "bg-blue-100 text-blue-800",
    pending: "bg-yellow-100 text-yellow-800",
    failed: "bg-rose-100 text-rose-800",
  };
  const cls = map[status ?? ""] ?? "bg-muted text-muted-foreground";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {status ?? "—"}
    </span>
  );
}

export default async function SearchPage() {
  const [runs, profiles] = await Promise.all([
    listRuns(10).catch(() => [] as RunMeta[]),
    listProfiles().catch(() => [] as CandidateProfile[]),
  ]);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Search Setup</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Run a discovery search to find new roles matching your profile.
        </p>
      </div>

      {/* Discovery launcher */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Search size={15} className="text-primary" />
            New Discovery Run
          </CardTitle>
        </CardHeader>
        <CardContent>
          {profiles.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                You need a candidate profile before running a discovery search.
              </p>
              <Link
                href="/profile/new"
                className="inline-flex items-center gap-1.5 text-sm text-primary font-medium hover:underline"
              >
                <UserCircle size={14} />
                Create a profile first
                <ArrowRight size={13} />
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Select a profile and optionally add a natural-language direction.
                The Intent Translator will allocate search queries across the
                most relevant lanes.
              </p>
              <StartDiscoveryButton profiles={profiles} />
            </div>
          )}
        </CardContent>
      </Card>

      {/* How it works */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground font-medium uppercase tracking-wide">
            How it works
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-2 text-sm text-muted-foreground list-none">
            {[
              "Your profile and instruction are translated into structured search lanes by the Intent Translator.",
              "The discovery agent runs queries across job boards and company career pages.",
              "New roles are classified, deduplicated, and added to the Role Inbox.",
              "Return here or go to Role Inbox to review newly discovered roles.",
            ].map((step, i) => (
              <li key={i} className="flex gap-3">
                <span className="shrink-0 w-5 h-5 rounded-full bg-muted text-xs font-semibold flex items-center justify-center text-foreground mt-0.5">
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {/* Recent runs */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Clock size={15} className="text-muted-foreground" />
              Recent Runs
            </CardTitle>
            {runs.length > 0 && (
              <Link href="/runs" className="text-xs text-primary hover:underline">
                View all →
              </Link>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No runs yet.</p>
          ) : (
            <div className="space-y-2">
              {runs.map((run) => (
                <Link
                  key={run.run_id}
                  href={`/runs/${run.run_id}`}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/40 transition-colors"
                >
                  <div>
                    <p className="text-sm font-medium font-mono">
                      {run.run_id.slice(0, 18)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {run.profile_name ?? "—"} · {fmtDate(run.run_timestamp)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {run.candidates_captured != null && (
                      <span className="text-xs text-muted-foreground">
                        {run.candidates_captured} jobs
                      </span>
                    )}
                    {statusBadge(run.status)}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
