import {
  getJob,
  getJobReport,
  listProfiles,
  listJobFitReports,
  type CandidateProfile,
  type FitReportSummary,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FitButton } from "@/components/fit-button";
import Link from "next/link";
import {
  ArrowLeft,
  AlertCircle,
  UserCircle,
  FileText,
  ExternalLink,
  CheckCircle2,
} from "lucide-react";
import { notFound } from "next/navigation";
import { AnalyzeButton } from "@/components/analyze-button";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ job_id: string }>;
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const color =
    score >= 70
      ? "bg-emerald-100 text-emerald-800"
      : score >= 50
      ? "bg-amber-100 text-amber-800"
      : "bg-rose-100 text-rose-800";
  return (
    <Badge className={`${color} border-0 text-xs font-semibold`}>
      {score}/100
    </Badge>
  );
}

function ExistingReport({
  report,
  profileId,
  jobId,
}: {
  report: FitReportSummary;
  profileId: string;
  jobId: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 flex-wrap py-2 border-t mt-3 pt-3 first:border-0 first:mt-0 first:pt-0">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 size={14} className="text-emerald-600" />
        <span>Report from {new Date(report.created_at).toLocaleDateString()}</span>
        {report.overall_match_score !== null && (
          <ScoreBadge score={report.overall_match_score} />
        )}
      </div>
      <div className="flex items-center gap-2">
        <Link href={`/fit-reports/${report.fit_report_id}`}>
          <Button size="sm" variant="outline">
            <FileText size={13} className="mr-1.5" />
            View Report
          </Button>
        </Link>
        <FitButton jobId={jobId} profileId={profileId} force={true} />
      </div>
    </div>
  );
}

export default async function FitAnalysisPage({ params }: PageProps) {
  const { job_id } = await params;

  const [job, report, profiles, fitReports] = await Promise.all([
    getJob(job_id).catch(() => null),
    getJobReport(job_id).catch(() => null),
    listProfiles().catch(() => [] as CandidateProfile[]),
    listJobFitReports(job_id).catch(() => [] as FitReportSummary[]),
  ]);

  if (!job) notFound();

  // Group fit reports by profile
  const reportsByProfile = new Map<string, FitReportSummary[]>();
  for (const fr of fitReports) {
    if (!fr.candidate_profile_id) continue;
    if (!reportsByProfile.has(fr.candidate_profile_id)) {
      reportsByProfile.set(fr.candidate_profile_id, []);
    }
    reportsByProfile.get(fr.candidate_profile_id)!.push(fr);
  }

  return (
    <div className="space-y-6">
      <Link
        href={`/jobs/${job_id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> Back to Job
      </Link>

      <div>
        <h1 className="text-2xl font-bold">Fit Analysis</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {job.title} · {job.company}
        </p>
      </div>

      {/* Step 1: Job Intelligence Report required */}
      {!report ? (
        <Card>
          <CardContent className="pt-6 pb-6 space-y-3">
            <div className="flex items-start gap-3">
              <AlertCircle size={18} className="text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Job Intelligence Report required</p>
                <p className="text-sm text-muted-foreground mt-1">
                  A Fit Report needs a Job Intelligence Report as input. Analyze this role first.
                </p>
              </div>
            </div>
            <div className="pl-7">
              <AnalyzeButton jobId={job_id} />
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Job report status */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <CheckCircle2 size={14} className="text-emerald-600" />
            <span>Job Intelligence Report available</span>
            <Link href={`/jobs/${job_id}/report`} className="inline-flex items-center gap-0.5 hover:text-foreground">
              View <ExternalLink size={11} className="ml-0.5" />
            </Link>
          </div>

          {/* No profiles */}
          {profiles.length === 0 ? (
            <Card>
              <CardContent className="pt-8 pb-8 text-center space-y-3">
                <UserCircle className="mx-auto text-muted-foreground" size={32} />
                <p className="font-medium">No candidate profiles yet</p>
                <p className="text-sm text-muted-foreground">
                  Create a profile to generate a Fit Report.
                </p>
                <Link href="/profile/new">
                  <Button size="sm" className="mt-2">Create Profile</Button>
                </Link>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {profiles.map((profile) => {
                const existing = reportsByProfile.get(profile.candidate_profile_id) ?? [];
                const latest = existing[0] ?? null;

                return (
                  <Card key={profile.candidate_profile_id}>
                    <CardContent className="pt-4 pb-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex items-start gap-3 flex-1 min-w-0">
                          <UserCircle size={18} className="text-muted-foreground mt-0.5 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="font-medium text-sm">
                              {profile.display_name ?? "Candidate Profile"}
                            </p>
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {profile.years_experience}y · {profile.domain_experience?.slice(0, 3).join(", ")}
                              {(profile.domain_experience?.length ?? 0) > 3 && "…"}
                            </p>
                          </div>
                        </div>

                        {/* If no existing report, show Generate button */}
                        {!latest && (
                          <FitButton jobId={job_id} profileId={profile.candidate_profile_id} />
                        )}
                      </div>

                      {/* Existing reports for this profile */}
                      {existing.length > 0 && (
                        <div>
                          {existing.map((r) => (
                            <ExistingReport
                              key={r.fit_report_id}
                              report={r}
                              profileId={profile.candidate_profile_id}
                              jobId={job_id}
                            />
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}

          <div className="text-xs text-muted-foreground">
            <Link href="/profile/new" className="hover:underline text-primary">
              + Add another candidate profile
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
