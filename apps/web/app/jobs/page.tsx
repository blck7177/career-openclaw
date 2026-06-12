import { listJobs, type Job } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Link from "next/link";
import { ExternalLink, Search } from "lucide-react";

export const dynamic = "force-dynamic";

function ConfidenceBadge({ c }: { c: string }) {
  if (c === "high") return <Badge className="bg-emerald-100 text-emerald-800 border-0 text-xs">High</Badge>;
  if (c === "medium") return <Badge className="bg-amber-100 text-amber-800 border-0 text-xs">Medium</Badge>;
  return <Badge className="bg-rose-100 text-rose-800 border-0 text-xs">Low</Badge>;
}

function FetchBadge({ status }: { status: string }) {
  if (status === "success") return <Badge className="bg-blue-100 text-blue-800 border-0 text-xs">Fetched</Badge>;
  return <Badge variant="outline" className="text-xs text-muted-foreground">{status}</Badge>;
}

// Shorten workstream label for display
function shortWs(ws: string) {
  return ws.replace(" / ", "\n").split("\n")[0];
}

interface PageProps {
  searchParams: Promise<{ workstream?: string; company?: string }>;
}

export default async function JobsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const jobs = await listJobs({
    workstream: params.workstream,
    company: params.company,
    limit: 500,
  }).catch(() => [] as Job[]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Jobs</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {jobs.length} job{jobs.length !== 1 ? "s" : ""}
            {params.workstream && <> · workstream: <span className="font-medium">{params.workstream}</span></>}
            {params.company && <> · company: <span className="font-medium">{params.company}</span></>}
          </p>
        </div>
        {(params.workstream || params.company) && (
          <Link href="/jobs" className="text-xs text-primary hover:underline">Clear filters</Link>
        )}
      </div>

      {/* Filter hint */}
      <div className="flex gap-2 items-center text-sm text-muted-foreground">
        <Search size={14} />
        <span>Filter by appending <code className="bg-muted px-1 rounded">?workstream=Market+Risk</code> or <code className="bg-muted px-1 rounded">?company=Goldman</code> to the URL.</span>
      </div>

      {/* Job list */}
      {jobs.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center">No jobs found.</p>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <Link
              key={job.job_id}
              href={`/jobs/${job.job_id}`}
              className="block border rounded-lg p-4 hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-foreground">{job.title}</span>
                    <ConfidenceBadge c={job.classification_confidence} />
                    <FetchBadge status={job.fetch_status} />
                    {job.possible_duplicate && (
                      <Badge className="bg-orange-100 text-orange-800 border-0 text-xs">Possible dup</Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {job.company} · {job.location}
                  </p>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    <Badge variant="secondary" className="text-xs">{shortWs(job.primary_workstream)}</Badge>
                    {job.secondary_workstreams?.slice(0, 2).map((ws) => (
                      <Badge key={ws} variant="outline" className="text-xs text-muted-foreground">{shortWs(ws)}</Badge>
                    ))}
                  </div>
                </div>
                <div className="text-right text-xs text-muted-foreground shrink-0">
                  <p>{job.date_found}</p>
                  <p className="mt-1">{job.run_id?.slice(0, 10)}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
