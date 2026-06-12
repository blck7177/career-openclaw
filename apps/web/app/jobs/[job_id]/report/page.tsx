import { getJob, getJobReport } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { ArrowLeft, AlertCircle } from "lucide-react";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ job_id: string }>;
}

export default async function JobReportPage({ params }: PageProps) {
  const { job_id } = await params;

  const [job, report] = await Promise.all([
    getJob(job_id).catch(() => null),
    getJobReport(job_id).catch(() => null),
  ]);

  return (
    <div className="space-y-6">
      <Link href={`/jobs/${job_id}`}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Back to Job
      </Link>

      <div>
        <h1 className="text-2xl font-bold">Job Intelligence Report</h1>
        {job && (
          <p className="text-muted-foreground text-sm mt-1">
            {job.title} · {job.company}
          </p>
        )}
      </div>

      {!report ? (
        <Card>
          <CardContent className="pt-8 pb-8 text-center space-y-3">
            <AlertCircle className="mx-auto text-muted-foreground" size={32} />
            <p className="text-sm text-muted-foreground">No Job Intelligence Report has been generated yet.</p>
            <p className="text-xs text-muted-foreground">
              Analysis will be triggerable via POST /api/jobs/{job_id}/analyze in Sprint 3.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Report meta */}
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>ID: <code className="bg-muted px-1 rounded">{report.job_report_id}</code></span>
            <span>Prompt: <code className="bg-muted px-1 rounded">{report.prompt_version}</code></span>
            {report.model && <span>Model: <code className="bg-muted px-1 rounded">{report.model}</code></span>}
            <Badge className="bg-emerald-100 text-emerald-800 border-0 text-xs">{report.status}</Badge>
            <span>{new Date(report.created_at).toLocaleDateString()}</span>
          </div>

          <Tabs defaultValue="narrative">
            <TabsList>
              <TabsTrigger value="narrative">Layer 1 — Narrative</TabsTrigger>
              <TabsTrigger value="structured">Layer 2 — Structured</TabsTrigger>
              {report.sources && <TabsTrigger value="sources">Sources</TabsTrigger>}
            </TabsList>

            <TabsContent value="narrative" className="mt-4">
              {report.narrative ? (
                <Card>
                  <CardContent className="pt-6">
                    <div
                      className="prose max-w-none text-sm"
                      dangerouslySetInnerHTML={{ __html: mdToHtml(report.narrative) }}
                    />
                  </CardContent>
                </Card>
              ) : (
                <p className="text-sm text-muted-foreground">Narrative report not available.</p>
              )}
            </TabsContent>

            <TabsContent value="structured" className="mt-4">
              {report.structured ? (
                <Card>
                  <CardContent className="pt-6">
                    <pre className="text-xs overflow-auto bg-muted p-4 rounded-lg max-h-[60vh]">
                      {JSON.stringify(report.structured, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              ) : (
                <p className="text-sm text-muted-foreground">Structured data not available.</p>
              )}
            </TabsContent>

            {report.sources && (
              <TabsContent value="sources" className="mt-4">
                <Card>
                  <CardContent className="pt-6">
                    <pre className="text-xs overflow-auto bg-muted p-4 rounded-lg max-h-[60vh]">
                      {JSON.stringify(report.sources, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              </TabsContent>
            )}
          </Tabs>
        </div>
      )}
    </div>
  );
}

// Minimal markdown → HTML for server-side rendering (no external deps)
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
