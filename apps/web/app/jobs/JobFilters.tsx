"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

interface Profile {
  candidate_profile_id: string;
  display_name?: string;
}

interface JobFiltersProps {
  profiles: Profile[];
  workstreams: string[];
}

export default function JobFilters({ profiles, workstreams }: JobFiltersProps) {
  const router = useRouter();
  const sp = useSearchParams();

  const update = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(sp.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      // Reset to page 1 on filter change
      router.push(`/jobs?${params.toString()}`);
    },
    [router, sp],
  );

  const profileId = sp.get("profile_id") ?? "";
  const workstream = sp.get("workstream") ?? "";
  const seniority = sp.get("seniority") ?? "";
  const confidence = sp.get("confidence") ?? "";

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {/* Profile selector — controls fit score overlay */}
      {profiles.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground whitespace-nowrap">Fit for:</span>
          <select
            value={profileId}
            onChange={(e) => update("profile_id", e.target.value || null)}
            className="h-7 rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring"
          >
            <option value="">— no profile —</option>
            {profiles.map((p) => (
              <option key={p.candidate_profile_id} value={p.candidate_profile_id}>
                {p.display_name ?? p.candidate_profile_id.slice(0, 12)}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Workstream filter */}
      {workstreams.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground whitespace-nowrap">Workstream:</span>
          <select
            value={workstream}
            onChange={(e) => update("workstream", e.target.value || null)}
            className="h-7 rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring max-w-[160px]"
          >
            <option value="">All</option>
            {workstreams.map((ws) => (
              <option key={ws} value={ws}>
                {ws.split(" / ")[0]}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Seniority filter */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-muted-foreground whitespace-nowrap">Seniority:</span>
        <select
          value={seniority}
          onChange={(e) => update("seniority", e.target.value || null)}
          className="h-7 rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All</option>
          <option value="junior">Junior</option>
          <option value="mid">Mid</option>
          <option value="senior">Senior</option>
          <option value="lead">Lead / Principal</option>
          <option value="director">Director+</option>
        </select>
      </div>

      {/* Confidence filter */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-muted-foreground whitespace-nowrap">Confidence:</span>
        <select
          value={confidence}
          onChange={(e) => update("confidence", e.target.value || null)}
          className="h-7 rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {/* Clear all */}
      {(profileId || workstream || seniority || confidence) && (
        <button
          onClick={() => router.push("/jobs")}
          className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
