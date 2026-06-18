"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { updateProfile, type CandidateProfile, type RepresentativeProject } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { ArrowLeft, Plus, Trash2, Loader2, AlertCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// Tag input — comma or Enter to add, × to remove
// ---------------------------------------------------------------------------

function TagInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && !value.includes(trimmed)) onChange([...value, trimmed]);
    setDraft("");
  }

  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      <div className="flex flex-wrap gap-1.5 min-h-[36px] border rounded-md px-3 py-2 bg-background focus-within:ring-2 focus-within:ring-ring">
        {value.map((tag) => (
          <Badge key={tag} variant="secondary" className="text-xs font-normal gap-1">
            {tag}
            <button
              type="button"
              onClick={() => onChange(value.filter((t) => t !== tag))}
              className="hover:text-destructive ml-0.5"
            >
              ×
            </button>
          </Badge>
        ))}
        <input
          className="flex-1 min-w-[120px] text-sm bg-transparent outline-none placeholder:text-muted-foreground"
          placeholder={placeholder ?? "Type and press Enter…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit();
            }
            if (e.key === "Backspace" && !draft && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={commit}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Project editor row
// ---------------------------------------------------------------------------

function ProjectRow({
  project,
  index,
  onChange,
  onRemove,
}: {
  project: RepresentativeProject;
  index: number;
  onChange: (p: RepresentativeProject) => void;
  onRemove: () => void;
}) {
  return (
    <Card className="border-dashed">
      <CardContent className="pt-4 pb-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Project {index + 1}
          </span>
          <Button type="button" size="sm" variant="ghost" onClick={onRemove} className="h-7 px-2 text-muted-foreground hover:text-destructive">
            <Trash2 size={13} />
          </Button>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Title <span className="text-muted-foreground font-normal">(optional)</span></label>
          <input
            className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="e.g. Regulatory Capital Model Validation"
            value={project.title ?? ""}
            onChange={(e) => onChange({ ...project, title: e.target.value })}
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Description <span className="text-destructive">*</span></label>
          <textarea
            className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
            rows={3}
            placeholder="What you did and the business context."
            value={project.description}
            onChange={(e) => onChange({ ...project, description: e.target.value })}
            required
          />
        </div>

        <TagInput
          label="Skills Used *"
          value={project.skills_used}
          onChange={(v) => onChange({ ...project, skills_used: v })}
          placeholder="Python, VaR, SQL…"
        />

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Quantified Impact <span className="text-muted-foreground font-normal">(optional)</span></label>
          <input
            className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="e.g. Reduced daily reconciliation time by 40%"
            value={project.quantified_impact ?? ""}
            onChange={(e) => onChange({ ...project, quantified_impact: e.target.value })}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main edit form
// ---------------------------------------------------------------------------

function emptyProject(): RepresentativeProject {
  return { title: "", description: "", skills_used: [], quantified_impact: "" };
}

interface EditProfileFormProps {
  profile: CandidateProfile;
}

export default function EditProfileForm({ profile }: EditProfileFormProps) {
  const router = useRouter();

  const [displayName, setDisplayName] = useState(profile.display_name ?? "");
  const [yearsExperience, setYearsExperience] = useState<number | "">(profile.years_experience);
  const [background, setBackground] = useState(profile.current_background);
  const [domainExp, setDomainExp] = useState<string[]>(profile.domain_experience ?? []);
  const [techSkills, setTechSkills] = useState<string[]>(profile.technical_skills ?? []);
  const [analyticalMethods, setAnalyticalMethods] = useState<string[]>(profile.analytical_methods ?? []);
  const [financeDomains, setFinanceDomains] = useState<string[]>(profile.finance_domains ?? []);
  const [tools, setTools] = useState<string[]>(profile.tools ?? []);
  const [projects, setProjects] = useState<RepresentativeProject[]>(
    profile.representative_projects?.length > 0
      ? profile.representative_projects
      : [emptyProject()],
  );
  const [targetRoles, setTargetRoles] = useState<string[]>(profile.target_roles ?? []);
  const [constraints, setConstraints] = useState(profile.constraints ?? "");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateProjectAt(i: number, p: RepresentativeProject) {
    setProjects(projects.map((proj, idx) => (idx === i ? p : proj)));
  }

  function removeProject(i: number) {
    setProjects(projects.filter((_, idx) => idx !== i));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!yearsExperience && yearsExperience !== 0) {
      setError("Years of experience is required.");
      return;
    }
    if (!background.trim()) {
      setError("Current background is required.");
      return;
    }
    const validProjects = projects.filter(
      (p) => p.description.trim() && p.skills_used.length > 0,
    );
    if (validProjects.length === 0) {
      setError("At least one project with a description and skills is required.");
      return;
    }

    setSubmitting(true);
    try {
      await updateProfile(profile.candidate_profile_id, {
        display_name: displayName || undefined,
        years_experience: Number(yearsExperience),
        current_background: background.trim(),
        domain_experience: domainExp,
        technical_skills: techSkills,
        analytical_methods: analyticalMethods,
        finance_domains: financeDomains,
        tools,
        representative_projects: validProjects.map((p) => ({
          title: p.title || undefined,
          description: p.description.trim(),
          skills_used: p.skills_used,
          quantified_impact: p.quantified_impact || undefined,
        })),
        target_roles: targetRoles.length > 0 ? targetRoles : undefined,
        constraints: constraints.trim() || undefined,
      });
      router.push("/profile");
      router.refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to update profile";
      setError(msg);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Link
        href="/profile"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> Back to Profiles
      </Link>

      <div>
        <h1 className="text-2xl font-bold">Edit Profile</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {profile.display_name ?? profile.candidate_profile_id.slice(0, 16)} ·{" "}
          <span className="font-mono text-xs">{profile.candidate_profile_id}</span>
        </p>
        <p className="text-xs text-amber-600 mt-2">
          Saving will refresh profile_version and invalidate any cached Fit Reports for this profile.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Section 1: Basic Info */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Basic Info</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Profile Label <span className="text-muted-foreground font-normal">(optional)</span></label>
              <input
                className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="e.g. Senior Risk Analyst — June 2026"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Years of Experience <span className="text-destructive">*</span></label>
              <input
                type="number"
                min={0}
                max={50}
                className="w-32 border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                value={yearsExperience}
                onChange={(e) => setYearsExperience(e.target.value === "" ? "" : Number(e.target.value))}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Current Background <span className="text-destructive">*</span></label>
              <textarea
                className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                rows={3}
                value={background}
                onChange={(e) => setBackground(e.target.value)}
                required
              />
            </div>
          </CardContent>
        </Card>

        {/* Section 2: Skills */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Experience & Skills</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <TagInput label="Domain Experience" value={domainExp} onChange={setDomainExp} placeholder="Market Risk, Credit Analytics…" />
            <TagInput label="Technical Skills" value={techSkills} onChange={setTechSkills} placeholder="Python, SQL, Bloomberg…" />
            <TagInput label="Analytical Methods" value={analyticalMethods} onChange={setAnalyticalMethods} placeholder="VaR, Greeks, Scenario Analysis…" />
            <TagInput label="Finance Domains" value={financeDomains} onChange={setFinanceDomains} placeholder="Equities, Fixed Income, Derivatives…" />
            <TagInput label="Tools & Platforms" value={tools} onChange={setTools} placeholder="Excel, Tableau, Murex, JIRA…" />
          </CardContent>
        </Card>

        {/* Section 3: Projects */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">
              Key Projects <span className="text-muted-foreground font-normal text-xs ml-1">(most important evidence for fit analysis)</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {projects.map((proj, i) => (
              <ProjectRow
                key={i}
                project={proj}
                index={i}
                onChange={(p) => updateProjectAt(i, p)}
                onRemove={() => removeProject(i)}
              />
            ))}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setProjects([...projects, emptyProject()])}
            >
              <Plus size={14} className="mr-1.5" />
              Add Project
            </Button>
          </CardContent>
        </Card>

        {/* Section 4: Targeting */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">
              Targeting <span className="text-muted-foreground font-normal text-xs ml-1">(optional)</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <TagInput label="Target Roles" value={targetRoles} onChange={setTargetRoles} placeholder="Risk Analyst, Quant Researcher…" />
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Constraints</label>
              <textarea
                className="w-full border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                rows={2}
                placeholder="Location, seniority level, or other requirements."
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {error && (
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle size={14} />
            <span>{error}</span>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting}>
            {submitting && <Loader2 size={14} className="animate-spin mr-1.5" />}
            {submitting ? "Saving…" : "Save Changes"}
          </Button>
          <Link href="/profile">
            <Button type="button" variant="ghost">Cancel</Button>
          </Link>
        </div>
      </form>
    </div>
  );
}
