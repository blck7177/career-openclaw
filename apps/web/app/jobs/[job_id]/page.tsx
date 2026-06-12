import { getJob, type Job } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { AnalyzeButton } from "@/components/analyze-button";
import Link from "next/link";
import { ArrowLeft, ExternalLink, FileText, Target } from "lucide-react";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{title}</h3>
      {children}
    </div>
  );
}

function TagList({ items }: { items: string[] }) {
  if (!items?.length) return <p className="text-sm text-muted-foreground">—</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <Badge key={item} variant="secondary" className="text-xs font-normal">{item}</Badge>
      ))}
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items?.length) return <p className="text-sm text-muted-foreground">—</p>;
  return (
    <ul className="text-sm space-y-1.5 text-foreground">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className="text-muted-foreground mt-0.5">·</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

interface PageProps {
  params: Promise<{ job_id: string }>;
}

export default async function JobDetailPage({ params }: PageProps) {
  const { job_id } = await params;
  let job: Job;
  try {
    job = await getJob(job_id);
  } catch {
    notFound();
  }

  const confColor =
    job.classification_confidence === "high"
      ? "bg-emerald-100 text-emerald-800"
      : job.classification_confidence === "medium"
      ? "bg-amber-100 text-amber-800"
      : "bg-rose-100 text-rose-800";

  return (
    <div className="space-y-6">
      {/* Back */}
      <Link href="/jobs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Back to Jobs
      </Link>

      {/* Title block */}
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">{job.title}</h1>
            <p className="text-muted-foreground mt-1">{job.company} · {job.location}</p>
          </div>
          <div className="flex gap-2 items-center shrink-0">
            <Badge className={`${confColor} border-0 text-xs`}>{job.classification_confidence}</Badge>
            <a href={job.source_url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
              Source <ExternalLink size={12} />
            </a>
          </div>
        </div>

        {/* Report link + action buttons */}
        <div className="flex gap-3 items-center flex-wrap">
          <Link href={`/jobs/${job.job_id}/report`}
                className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <FileText size={14} /> View Job Intelligence Report
          </Link>
          <AnalyzeButton jobId={job.job_id} />
          <Link href={`/jobs/${job.job_id}/fit`}>
            <Button size="sm" variant="outline">
              <Target size={14} className="mr-1.5" />
              Fit Analysis
            </Button>
          </Link>
        </div>

        {/* Workstreams */}
        <div className="flex flex-wrap gap-1.5 mt-1">
          <Badge variant="secondary" className="text-xs">{job.primary_workstream}</Badge>
          {job.secondary_workstreams?.map((ws) => (
            <Badge key={ws} variant="outline" className="text-xs text-muted-foreground">{ws}</Badge>
          ))}
        </div>
      </div>

      <Separator />

      {/* Metadata row */}
      <div className="grid grid-cols-4 gap-4 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Date found</p>
          <p className="font-medium">{job.date_found}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Seniority</p>
          <p className="font-medium capitalize">{job.seniority_inferred ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Source type</p>
          <p className="font-medium">{job.source_type}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Run ID</p>
          <Link href={`/runs/${job.run_id}`} className="font-medium text-primary hover:underline text-xs">
            {job.run_id}
          </Link>
        </div>
      </div>

      <Separator />

      {/* Main content grid */}
      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Required Skills</CardTitle>
          </CardHeader>
          <CardContent>
            <BulletList items={job.required_skills} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Preferred Skills</CardTitle>
          </CardHeader>
          <CardContent>
            <BulletList items={job.preferred_skills} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Responsibilities</CardTitle>
        </CardHeader>
        <CardContent>
          <BulletList items={job.responsibilities} />
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Likely Tasks</CardTitle>
          </CardHeader>
          <CardContent>
            <BulletList items={job.likely_tasks} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Stakeholders</CardTitle>
          </CardHeader>
          <CardContent>
            <BulletList items={job.likely_stakeholders} />
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Tools</CardTitle>
          </CardHeader>
          <CardContent>
            <TagList items={job.tools_mentioned} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Finance Domains</CardTitle>
          </CardHeader>
          <CardContent>
            <TagList items={job.finance_domains} />
          </CardContent>
        </Card>
      </div>

      {job.inferred_team_context && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Inferred Team Context</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed">{job.inferred_team_context}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
