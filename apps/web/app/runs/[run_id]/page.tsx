import { getRun, getRunSummaryMd, type RunDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, XCircle, Circle, AlertCircle } from "lucide-react";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ run_id: string }>;
}

function StatRow({ label, value }: { label: string; value: number | string | undefined | null }) {
  return (
    <div className="flex justify-between text-sm py-1.5 border-b border-border/60 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value ?? "—"}</span>
    </div>
  );
}

export default async function RunDetailPage({ params }: PageProps) {
  const { run_id } = await params;

  let run: RunDetail;
  try {
    run = await getRun(run_id);
  } catch {
    notFound();
  }

  const md = run.has_summary_md
    ? await getRunSummaryMd(run_id).catch(() => null)
    : null;

  const s = run.summary;
  const topWs = s?.top_workstreams ?? [];

  return (
    <div className="space-y-6">
      <Link href="/runs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      {/* Header */}
      <div>
        <div className="flex items-start justify-between">
          <h1 className="text-2xl font-bold font-mono">{run_id}</h1>
          <StatusBadge status={run.status} />
        </div>
        <p className="text-muted-foreground text-sm mt-1">
          {run.profile_name ?? "—"} · {run.mode ?? "—"} ·{" "}
          {run.run_timestamp ? new Date(run.run_timestamp).toLocaleString() : "—"}
        </p>
      </div>

      <Separator />

      <Tabs defaultValue={md ? "summary" : "stats"}>
        <TabsList>
          {md && <TabsTrigger value="summary">Summary</TabsTrigger>}
          <TabsTrigger value="stats">Stats</TabsTrigger>
          {s?.fetch_failures && s.fetch_failures.length > 0 && (
            <TabsTrigger value="failures">Fetch Failures ({s.fetch_failures.length})</TabsTrigger>
          )}
        </TabsList>

        {/* Markdown summary */}
        {md && (
          <TabsContent value="summary" className="mt-4">
            <Card>
              <CardContent className="pt-6">
                <div
                  className="prose max-w-none text-sm"
                  dangerouslySetInnerHTML={{ __html: mdToHtml(md) }}
                />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Stats */}
        <TabsContent value="stats" className="mt-4">
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Discovery Results</CardTitle>
              </CardHeader>
              <CardContent>
                {/* Prefer split counters; fall back to jobs_saved for legacy runs */}
                {(s as Record<string, unknown>)?.new_jobs_inserted != null ? (
                  <>
                    <StatRow
                      label="New roles inserted"
                      value={(s as Record<string, unknown>).new_jobs_inserted as number}
                    />
                    <StatRow
                      label="Existing updated"
                      value={(s as Record<string, unknown>).existing_jobs_updated as number}
                    />
                    {((s as Record<string, unknown>).possible_duplicates as number) > 0 && (
                      <StatRow
                        label="Possible duplicates"
                        value={(s as Record<string, unknown>).possible_duplicates as number}
                      />
                    )}
                  </>
                ) : (
                  <StatRow label="Saved to DB" value={s?.jobs_saved} />
                )}
                <StatRow label="Candidates captured" value={s?.jobs_discovered} />
                <StatRow label="Fetched" value={s?.jobs_fetched} />
                <StatRow label="Structured" value={s?.jobs_structured} />
                <StatRow label="Failed" value={s?.jobs_failed} />
                <StatRow
                  label="Duration"
                  value={s?.duration_seconds != null ? `${s.duration_seconds}s` : undefined}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Top Workstreams</CardTitle>
              </CardHeader>
              <CardContent>
                {topWs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">—</p>
                ) : (
                  <div className="space-y-2">
                    {topWs.map(({ workstream, count }) => (
                      <div key={workstream} className="flex justify-between items-center text-sm">
                        <span className="text-muted-foreground truncate max-w-[180px]">{workstream}</span>
                        <Badge variant="secondary" className="text-xs tabular-nums">{count}</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Search config */}
          {run.run_timestamp && (
            <Card className="mt-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Run Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                <StatRow label="Profile" value={run.profile_name} />
                <StatRow label="Mode" value={run.mode} />
                <StatRow label="Status" value={run.status} />
                <StatRow label="Started" value={run.run_timestamp ? new Date(run.run_timestamp).toLocaleString() : null} />
                <StatRow label="Search completed" value={run.search_completed_at ? new Date(run.search_completed_at).toLocaleString() : null} />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Fetch failures */}
        {s?.fetch_failures && s.fetch_failures.length > 0 && (
          <TabsContent value="failures" className="mt-4">
            <Card>
              <CardContent className="pt-4">
                <pre className="text-xs overflow-auto bg-muted p-4 rounded-lg max-h-96">
                  {JSON.stringify(s.fetch_failures, null, 2)}
                </pre>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
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

function mdToHtml(md: string): string {
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^#{3}\s(.+)$/gm, "<h3>$1</h3>")
    .replace(/^#{2}\s(.+)$/gm, "<h2>$1</h2>")
    .replace(/^#{1}\s(.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\|(.+)\|/g, (m) => {
      const cells = m.split("|").filter(Boolean).map(c => c.trim());
      return "<tr>" + cells.map(c => `<td>${c}</td>`).join("") + "</tr>";
    })
    .replace(/(<tr>.*<\/tr>\n?)+/gs, (block) => `<table>${block}</table>`)
    .replace(/^\s*[-*]\s(.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*?<\/li>\n?)+/gs, (block) => `<ul>${block}</ul>`)
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/^(?![<])(.+)$/gm, (m) => m.trim() ? m : "");
}
