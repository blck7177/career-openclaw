import { getFitReport, getJob, getProfile, type FitReport } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Flag,
  MessageSquare,
  FileEdit,
  Tags,
  Lightbulb,
  ChevronRight,
} from "lucide-react";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ fit_report_id: string }>;
}

// ---------------------------------------------------------------------------
// Score display
// ---------------------------------------------------------------------------

function ScoreRing({ score }: { score: number }) {
  const color =
    score >= 70 ? "text-emerald-600" : score >= 50 ? "text-amber-600" : "text-rose-600";
  const label =
    score >= 70 ? "Strong Match" : score >= 50 ? "Partial Match" : "Significant Gaps";
  return (
    <div className="flex items-center gap-4">
      <div className={`text-5xl font-bold tabular-nums ${color}`}>{score}</div>
      <div>
        <div className="text-sm font-medium text-muted-foreground">/ 100</div>
        <Badge
          className={`mt-1 border-0 text-xs font-semibold ${
            score >= 70
              ? "bg-emerald-100 text-emerald-800"
              : score >= 50
              ? "bg-amber-100 text-amber-800"
              : "bg-rose-100 text-rose-800"
          }`}
        >
          {label}
        </Badge>
      </div>
    </div>
  );
}

function ActionBadge({ action }: { action: string }) {
  const config: Record<string, { label: string; cls: string }> = {
    "apply now":           { label: "Apply Now",            cls: "bg-emerald-100 text-emerald-800" },
    "revise resume first": { label: "Revise Resume First",  cls: "bg-amber-100 text-amber-800" },
    "get more context":    { label: "Get More Context",     cls: "bg-blue-100 text-blue-800" },
    skip:                  { label: "Skip",                 cls: "bg-slate-100 text-slate-700" },
  };
  const c = config[action.toLowerCase()] ?? { label: action, cls: "bg-muted text-foreground" };
  return <Badge className={`${c.cls} border-0 text-xs font-semibold`}>{c.label}</Badge>;
}

// ---------------------------------------------------------------------------
// Severity badge for gaps
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === "blocking") return <Badge className="bg-rose-100 text-rose-800 border-0 text-xs">Blocking</Badge>;
  if (severity === "significant") return <Badge className="bg-amber-100 text-amber-800 border-0 text-xs">Significant</Badge>;
  return <Badge className="bg-slate-100 text-slate-700 border-0 text-xs">Minor</Badge>;
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({
  icon: Icon,
  title,
  children,
  count,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          <Icon size={16} className="text-muted-foreground" />
          {title}
          {count !== undefined && (
            <Badge variant="secondary" className="text-xs font-normal ml-1">
              {count}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default async function FitReportPage({ params }: PageProps) {
  const { fit_report_id } = await params;

  const result = await getFitReport(fit_report_id).catch(() => null);
  if (!result) notFound();

  const { structured: r, narrative_md } = result;

  const [job, profile] = await Promise.all([
    getJob(r.job_id).catch(() => null),
    getProfile(r.candidate_profile_id).catch(() => null),
  ]);

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href={job ? `/jobs/${r.job_id}/fit` : "/jobs"}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> Back to Fit Analysis
      </Link>

      {/* Header */}
      <div className="space-y-1">
        <h1 className="text-2xl font-bold">Candidate Fit Report</h1>
        {job && (
          <p className="text-muted-foreground text-sm">
            {job.title} · {job.company}
            {job.location && <> · {job.location}</>}
          </p>
        )}
        {profile && (
          <p className="text-muted-foreground text-sm">
            Profile: <span className="font-medium text-foreground">
              {profile.display_name ?? "Candidate Profile"}
            </span>
            {" "}· {profile.years_experience}y experience
          </p>
        )}
      </div>

      {/* Score + summary card */}
      <Card>
        <CardContent className="pt-6 pb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="space-y-3">
              <ScoreRing score={r.overall_match_score} />
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Recommended action:</span>
                <ActionBadge action={r.recommended_next_action} />
              </div>
            </div>
            <div className="sm:max-w-md text-sm text-muted-foreground leading-relaxed">
              {r.match_summary}
            </div>
          </div>

          {/* Meta row */}
          <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t text-xs text-muted-foreground">
            <span>Report: <code className="bg-muted px-1 rounded">{fit_report_id}</code></span>
            <span>Prompt: <code className="bg-muted px-1 rounded">{r.prompt_version}</code></span>
            <span>{new Date(r.analyzed_at).toLocaleDateString()}</span>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="analysis">
        <TabsList>
          <TabsTrigger value="analysis">Match Analysis</TabsTrigger>
          <TabsTrigger value="positioning">Resume Positioning</TabsTrigger>
          {narrative_md && <TabsTrigger value="narrative">Narrative</TabsTrigger>}
        </TabsList>

        {/* ── Analysis tab ────────────────────────────────────────────── */}
        <TabsContent value="analysis" className="mt-4 space-y-4">

          {/* Strong matches */}
          {r.strong_matches?.length > 0 && (
            <Section icon={CheckCircle2} title="Strong Matches" count={r.strong_matches.length}>
              <div className="space-y-3">
                {r.strong_matches.map((m, i) => (
                  <div key={i} className="border rounded-md p-3 bg-emerald-50/40">
                    <p className="text-sm font-medium text-emerald-900">{m.demand}</p>
                    {m.evidence && (
                      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{m.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Partial matches */}
          {r.partial_matches?.length > 0 && (
            <Section icon={AlertTriangle} title="Partial Matches" count={r.partial_matches.length}>
              <div className="space-y-3">
                {r.partial_matches.map((m, i) => (
                  <div key={i} className="border rounded-md p-3 bg-amber-50/40">
                    <p className="text-sm font-medium text-amber-900">{m.demand}</p>
                    {m.gap_description && (
                      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{m.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Gaps */}
          {r.gaps?.length > 0 && (
            <Section icon={XCircle} title="Gaps" count={r.gaps.length}>
              <div className="space-y-3">
                {r.gaps.map((g, i) => (
                  <div key={i} className="border rounded-md p-3 bg-rose-50/30">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-rose-900">{g.demand}</p>
                      <SeverityBadge severity={g.severity} />
                    </div>
                    {g.gap_description && (
                      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{g.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Risk flags */}
          {r.risk_flags?.length > 0 && (
            <Section icon={Flag} title="Risk Flags" count={r.risk_flags.length}>
              <ul className="space-y-2">
                {r.risk_flags.map((flag, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-rose-700">
                    <Flag size={13} className="mt-0.5 shrink-0" />
                    {flag}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* Interview talking points */}
          {r.interview_talking_points?.length > 0 && (
            <Section icon={MessageSquare} title="Interview Talking Points">
              <ol className="space-y-2 list-none">
                {r.interview_talking_points.map((point, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{point}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </TabsContent>

        {/* ── Resume Positioning tab ───────────────────────────────────── */}
        <TabsContent value="positioning" className="mt-4 space-y-4">
          {r.resume_rewrite_strategy ? (
            <>
              {r.resume_rewrite_strategy.positioning && (
                <Section icon={FileEdit} title="Resume Positioning Guidance">
                  <p className="text-sm leading-relaxed text-foreground">
                    {r.resume_rewrite_strategy.positioning}
                  </p>
                </Section>
              )}

              {r.resume_rewrite_strategy.keywords_to_add?.length > 0 && (
                <Section icon={Tags} title="Keywords to Add" count={r.resume_rewrite_strategy.keywords_to_add.length}>
                  <div className="flex flex-wrap gap-2">
                    {r.resume_rewrite_strategy.keywords_to_add.map((kw) => (
                      <Badge key={kw} variant="secondary" className="text-xs font-normal">
                        {kw}
                      </Badge>
                    ))}
                  </div>
                </Section>
              )}

              {r.resume_rewrite_strategy.evidence_to_surface?.length > 0 && (
                <Section icon={Lightbulb} title="Evidence to Surface">
                  <ul className="space-y-2">
                    {r.resume_rewrite_strategy.evidence_to_surface.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        <ChevronRight size={14} className="shrink-0 mt-0.5 text-muted-foreground" />
                        <span className="leading-relaxed">{item}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <p className="text-xs text-muted-foreground">
                Bullet-level rewrite guidance will be available after resume upload is implemented.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No positioning guidance available.</p>
          )}
        </TabsContent>

        {/* ── Narrative tab ────────────────────────────────────────────── */}
        {narrative_md && (
          <TabsContent value="narrative" className="mt-4">
            <Card>
              <CardContent className="pt-6">
                <div
                  className="prose max-w-none text-sm"
                  dangerouslySetInnerHTML={{ __html: mdToHtml(narrative_md) }}
                />
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>

      {/* Footer action */}
      <div className="flex items-center gap-3 pt-2 border-t">
        {job && (
          <Link href={`/jobs/${r.job_id}/fit`}>
            <Button size="sm" variant="outline">Back to Fit Analysis</Button>
          </Link>
        )}
        {job && (
          <Link href={`/jobs/${r.job_id}/report`}>
            <Button size="sm" variant="ghost">View Job Intelligence Report</Button>
          </Link>
        )}
      </div>
    </div>
  );
}

// Minimal markdown → HTML (same as job report page)
function mdToHtml(md: string): string {
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^#{3}\s(.+)$/gm, "<h3>$1</h3>")
    .replace(/^#{2}\s(.+)$/gm, "<h2>$1</h2>")
    .replace(/^#{1}\s(.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^\s*[-*]\s(.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/^(?!<[hul])(.+)$/gm, (m) => m.trim() ? m : "")
    .replace(/\n/g, "<br>");
}
