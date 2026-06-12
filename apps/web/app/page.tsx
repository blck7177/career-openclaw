import { listJobs, listRuns, type Job, type RunMeta } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Briefcase, PlayCircle, TrendingUp, Clock } from "lucide-react";

export const dynamic = "force-dynamic";

// Derive workstream coverage counts from jobs
function buildWorkstreamCounts(jobs: Job[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const job of jobs) {
    const ws = job.primary_workstream ?? "Unknown";
    counts[ws] = (counts[ws] ?? 0) + 1;
  }
  return counts;
}

function confidenceBadge(c: string) {
  if (c === "high") return <Badge className="bg-emerald-100 text-emerald-800 border-0 text-xs">High</Badge>;
  if (c === "medium") return <Badge className="bg-amber-100 text-amber-800 border-0 text-xs">Medium</Badge>;
  return <Badge className="bg-rose-100 text-rose-800 border-0 text-xs">Low</Badge>;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default async function DashboardPage() {
  const [jobs, runs] = await Promise.all([
    listJobs({ limit: 500 }).catch(() => [] as Job[]),
    listRuns(10).catch(() => [] as RunMeta[]),
  ]);

  const wsCounts = buildWorkstreamCounts(jobs);
  const wsEntries = Object.entries(wsCounts).sort((a, b) => b[1] - a[1]);
  const maxCount = wsEntries[0]?.[1] ?? 1;

  const highConf = jobs.filter((j) => j.classification_confidence === "high").length;
  const recentRuns = runs.slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">Job intelligence overview · dev_default workspace</p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Jobs</p>
                <p className="text-3xl font-bold mt-1">{jobs.length}</p>
              </div>
              <Briefcase className="text-primary/40" size={32} />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">High Confidence</p>
                <p className="text-3xl font-bold mt-1">{highConf}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {jobs.length ? Math.round((highConf / jobs.length) * 100) : 0}% of total
                </p>
              </div>
              <TrendingUp className="text-emerald-400/60" size={32} />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Search Runs</p>
                <p className="text-3xl font-bold mt-1">{runs.length}</p>
              </div>
              <PlayCircle className="text-primary/40" size={32} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Workstream coverage */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Workstream Coverage</CardTitle>
        </CardHeader>
        <CardContent>
          {wsEntries.length === 0 ? (
            <p className="text-sm text-muted-foreground">No data yet.</p>
          ) : (
            <div className="space-y-2.5">
              {wsEntries.map(([ws, count]) => (
                <div key={ws} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <Link href={`/jobs?workstream=${encodeURIComponent(ws)}`}
                          className="text-foreground hover:text-primary truncate max-w-xs">{ws}</Link>
                    <span className="text-muted-foreground font-mono text-xs">{count}</span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary/70 rounded-full"
                      style={{ width: `${(count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent runs */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Recent Runs</CardTitle>
            <Link href="/runs" className="text-xs text-primary hover:underline">View all →</Link>
          </div>
        </CardHeader>
        <CardContent>
          {recentRuns.length === 0 ? (
            <p className="text-sm text-muted-foreground">No runs found.</p>
          ) : (
            <div className="space-y-2">
              {recentRuns.map((run) => (
                <Link key={run.run_id} href={`/runs/${run.run_id}`}
                      className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
                  <div className="flex items-center gap-3">
                    <Clock size={14} className="text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{run.run_id}</p>
                      <p className="text-xs text-muted-foreground">{run.profile_name ?? "—"}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 text-right">
                    {run.candidates_captured != null && (
                      <span className="text-xs text-muted-foreground">{run.candidates_captured} jobs</span>
                    )}
                    <Badge variant="outline" className="text-xs capitalize">{run.status ?? "—"}</Badge>
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
