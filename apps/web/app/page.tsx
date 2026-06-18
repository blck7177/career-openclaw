import {
  listJobs,
  listRuns,
  listProfiles,
  listFitReportsByProfile,
  type Job,
  type RunMeta,
  type CandidateProfile,
  type ProfileFitReportSummary,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Briefcase, Clock, ArrowRight, Sparkles, Target } from "lucide-react";
import StartDiscoveryButton from "@/components/StartDiscoveryButton";

export const dynamic = "force-dynamic";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function scoreBadge(score: number | null) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const cls =
    pct >= 75
      ? "bg-emerald-100 text-emerald-800"
      : pct >= 50
      ? "bg-amber-100 text-amber-800"
      : "bg-rose-100 text-rose-800";
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border-0 ${cls}`}>
      {pct}%
    </span>
  );
}

function runStatusBadge(status: string | null) {
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

// Jobs found in the last N days
function recentHighConfJobs(jobs: Job[], days = 7): Job[] {
  const cutoff = Date.now() - days * 86_400_000;
  return jobs.filter(
    (j) =>
      j.classification_confidence === "high" &&
      j.date_found &&
      new Date(j.date_found).getTime() > cutoff,
  );
}

export default async function CommandCenterPage() {
  const [jobs, runsRaw, profiles] = await Promise.all([
    listJobs({ limit: 500 }).catch(() => [] as Job[]),
    listRuns(5).catch(() => [] as RunMeta[]),
    listProfiles().catch(() => [] as CandidateProfile[]),
  ]);
  const runs = Array.isArray(runsRaw) ? runsRaw : [];

  // Fetch fit reports for the first profile (most recently created)
  const primaryProfile = profiles[0] ?? null;
  const fitReports: ProfileFitReportSummary[] = primaryProfile
    ? await listFitReportsByProfile(primaryProfile.candidate_profile_id).catch(
        () => [],
      )
    : [];

  const recentJobs = recentHighConfJobs(jobs);
  const latestRun = runs[0] ?? null;

  // Build a job_id → title lookup for fit report rows
  const jobTitleMap = Object.fromEntries(
    jobs.map((j) => [j.job_id, { title: j.title, company: j.company }]),
  );

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Command Center</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {jobs.length} roles in catalog
            {recentJobs.length > 0 && (
              <> · <span className="text-emerald-600 font-medium">{recentJobs.length} high-confidence new this week</span></>
            )}
          </p>
        </div>
        {/* Discovery CTA — only shown when profiles exist */}
        {profiles.length > 0 && (
          <StartDiscoveryButton profiles={profiles} />
        )}
      </div>

      {/* Onboarding nudge when no data yet */}
      {profiles.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-10 text-center space-y-3">
            <Target className="mx-auto text-muted-foreground" size={36} />
            <p className="font-medium">Set up your profile to get started</p>
            <p className="text-sm text-muted-foreground">
              Create a candidate profile, then run a discovery search to find matching roles.
            </p>
            <Link
              href="/profile/new"
              className="inline-flex items-center gap-1.5 text-sm text-primary font-medium hover:underline mt-2"
            >
              Create profile <ArrowRight size={14} />
            </Link>
          </CardContent>
        </Card>
      )}

      {/* Fit Reports summary — decisions waiting */}
      {fitReports.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Sparkles size={15} className="text-primary" />
                Fit Analyses
                {primaryProfile && (
                  <span className="text-xs font-normal text-muted-foreground">
                    · {primaryProfile.display_name ?? primaryProfile.candidate_profile_id.slice(0, 12)}
                  </span>
                )}
              </CardTitle>
              <Link href="/roles" className="text-xs text-primary hover:underline">
                Browse all roles →
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {fitReports.slice(0, 6).map((fr) => {
                const jobInfo = jobTitleMap[fr.job_id];
                return (
                  <Link
                    key={fr.fit_report_id}
                    href={`/fit-reports/${fr.fit_report_id}`}
                    className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/40 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {jobInfo?.title ?? fr.job_id}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        {jobInfo?.company ?? ""}
                        {fr.recommended_next_action && (
                          <> · {fr.recommended_next_action}</>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-3 ml-3 shrink-0">
                      {scoreBadge(fr.overall_match_score)}
                      <span className="text-xs text-muted-foreground">
                        {fmtDate(fr.created_at)}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent high-confidence jobs */}
      {recentJobs.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Briefcase size={15} className="text-primary" />
                New This Week
              </CardTitle>
              <Link href="/roles" className="text-xs text-primary hover:underline">
                Role Inbox →
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recentJobs.slice(0, 5).map((job) => (
                <Link
                  key={job.job_id}
                  href={`/jobs/${job.job_id}`}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/40 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{job.title}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {job.company} · {job.location}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 ml-3 shrink-0">
                    <Badge variant="secondary" className="text-xs">
                      {job.primary_workstream?.split(" / ")[0] ?? "—"}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {fmtDate(job.date_found)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent search runs */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Clock size={15} className="text-muted-foreground" />
              Recent Searches
            </CardTitle>
            <Link href="/search" className="text-xs text-primary hover:underline">
              New search →
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No searches yet.{" "}
              <Link href="/search" className="text-primary hover:underline">
                Start your first discovery run.
              </Link>
            </p>
          ) : (
            <div className="space-y-2">
              {runs.map((run) => (
                <Link
                  key={run.run_id}
                  href={`/runs/${run.run_id}`}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/40 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div>
                      <p className="text-sm font-medium font-mono">
                        {run.run_id.slice(0, 14)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {run.profile_name ?? "—"}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {run.candidates_captured != null && (
                      <span className="text-xs text-muted-foreground">
                        {run.candidates_captured} jobs
                      </span>
                    )}
                    {runStatusBadge(run.status)}
                    <span className="text-xs text-muted-foreground">
                      {fmtDate(run.run_timestamp)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Search nudge when no runs and profiles exist */}
      {runs.length === 0 && profiles.length > 0 && (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center space-y-3">
            <p className="text-sm text-muted-foreground">
              You have a profile but no search runs yet.
            </p>
            <StartDiscoveryButton profiles={profiles} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
