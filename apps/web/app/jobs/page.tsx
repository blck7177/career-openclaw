import {
  listJobs,
  listProfiles,
  listFitReportsByProfile,
  type Job,
  type CandidateProfile,
  type ProfileFitReportSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Suspense } from "react";
import JobFilters from "./JobFilters";

export const dynamic = "force-dynamic";

function ConfidenceBadge({ c }: { c: string }) {
  if (c === "high") return <Badge className="bg-emerald-100 text-emerald-800 border-0 text-xs">High</Badge>;
  if (c === "medium") return <Badge className="bg-amber-100 text-amber-800 border-0 text-xs">Medium</Badge>;
  return <Badge className="bg-rose-100 text-rose-800 border-0 text-xs">Low</Badge>;
}

function FitScoreBadge({
  fitReportId,
  score,
}: {
  fitReportId: string;
  score: number | null;
}) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const cls =
    pct >= 75
      ? "bg-emerald-100 text-emerald-800"
      : pct >= 50
      ? "bg-amber-100 text-amber-800"
      : "bg-rose-100 text-rose-800";
  return (
    <Link
      href={`/fit-reports/${fitReportId}`}
      onClick={(e) => e.stopPropagation()}
      className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cls} hover:opacity-80 transition-opacity`}
    >
      {pct}% fit
    </Link>
  );
}

function shortWs(ws: string) {
  return ws.split(" / ")[0];
}

// Derive unique workstreams for filter panel
function uniqueWorkstreams(jobs: Job[]): string[] {
  const set = new Set<string>();
  for (const j of jobs) {
    if (j.primary_workstream) set.add(j.primary_workstream);
  }
  return [...set].sort();
}

interface PageProps {
  searchParams: Promise<{
    workstream?: string;
    company?: string;
    seniority?: string;
    confidence?: string;
    profile_id?: string;
  }>;
}

export default async function JobsPage({ searchParams }: PageProps) {
  const params = await searchParams;

  const [allJobs, profiles] = await Promise.all([
    listJobs({
      workstream: params.workstream,
      company: params.company,
      limit: 500,
    }).catch(() => [] as Job[]),
    listProfiles().catch(() => [] as CandidateProfile[]),
  ]);

  // Client-side seniority filter (backend doesn't support it yet)
  let jobs = allJobs;
  if (params.seniority) {
    const term = params.seniority.toLowerCase();
    jobs = jobs.filter((j) =>
      j.seniority_inferred?.toLowerCase().includes(term),
    );
  }
  if (params.confidence) {
    jobs = jobs.filter((j) => j.classification_confidence === params.confidence);
  }

  // Fetch fit reports for the selected profile
  const fitMap = new Map<string, ProfileFitReportSummary>();
  if (params.profile_id) {
    const fitReports = await listFitReportsByProfile(params.profile_id).catch(
      () => [] as ProfileFitReportSummary[],
    );
    // Keep only the latest fit report per job
    for (const fr of fitReports) {
      if (!fitMap.has(fr.job_id)) {
        fitMap.set(fr.job_id, fr);
      }
    }
    // Sort jobs: fit-score descending first, then unanalyzed at the end
    jobs = [...jobs].sort((a, b) => {
      const fa = fitMap.get(a.job_id);
      const fb = fitMap.get(b.job_id);
      const sa = fa?.overall_match_score ?? -1;
      const sb = fb?.overall_match_score ?? -1;
      return sb - sa;
    });
  }

  const workstreams = uniqueWorkstreams(allJobs);
  const activeFilters = [
    params.profile_id,
    params.workstream,
    params.seniority,
    params.confidence,
    params.company,
  ].filter(Boolean).length;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Role Inbox</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {jobs.length} role{jobs.length !== 1 ? "s" : ""}
          {activeFilters > 0 && (
            <> · {activeFilters} filter{activeFilters !== 1 ? "s" : ""} active</>
          )}
        </p>
      </div>

      {/* Filter panel — client component */}
      <Suspense fallback={null}>
        <JobFilters profiles={profiles} workstreams={workstreams} />
      </Suspense>

      {/* Job list */}
      {jobs.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center">No roles match the current filters.</p>
      ) : (
        <div className="space-y-2.5">
          {jobs.map((job) => {
            const fr = fitMap.get(job.job_id);
            return (
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
                      {job.possible_duplicate && (
                        <Badge className="bg-orange-100 text-orange-800 border-0 text-xs">Dup</Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {job.company} · {job.location}
                    </p>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      <Badge variant="secondary" className="text-xs">
                        {shortWs(job.primary_workstream)}
                      </Badge>
                      {job.secondary_workstreams?.slice(0, 2).map((ws) => (
                        <Badge key={ws} variant="outline" className="text-xs text-muted-foreground">
                          {shortWs(ws)}
                        </Badge>
                      ))}
                      {job.seniority_inferred && (
                        <Badge variant="outline" className="text-xs text-muted-foreground">
                          {job.seniority_inferred}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0 ml-2">
                    {fr ? (
                      <FitScoreBadge
                        fitReportId={fr.fit_report_id}
                        score={fr.overall_match_score}
                      />
                    ) : params.profile_id ? (
                      <Link
                        href={`/jobs/${job.job_id}/fit`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs text-muted-foreground hover:text-primary underline underline-offset-2"
                      >
                        Analyze fit
                      </Link>
                    ) : null}
                    <span className="text-xs text-muted-foreground">
                      {job.date_found}
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
