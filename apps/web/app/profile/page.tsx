import { listProfiles, type CandidateProfile } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { UserCircle, Plus, Briefcase, Pencil } from "lucide-react";

export const dynamic = "force-dynamic";

function ProfileCard({ profile }: { profile: CandidateProfile }) {
  const domainPreview = profile.domain_experience?.slice(0, 3) ?? [];
  const hasMore = (profile.domain_experience?.length ?? 0) > 3;

  return (
    <Card className="hover:bg-muted/40 transition-colors">
      <CardContent className="pt-5 pb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className="mt-0.5 shrink-0 text-muted-foreground">
              <UserCircle size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-foreground">
                {profile.display_name ?? "Candidate Profile"}
              </p>
              <p className="text-sm text-muted-foreground mt-0.5">
                {profile.years_experience} years experience
              </p>
              {profile.current_background && (
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                  {profile.current_background}
                </p>
              )}
              {domainPreview.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {domainPreview.map((d) => (
                    <Badge key={d} variant="secondary" className="text-xs font-normal">
                      {d}
                    </Badge>
                  ))}
                  {hasMore && (
                    <Badge variant="outline" className="text-xs text-muted-foreground">
                      +{profile.domain_experience.length - 3} more
                    </Badge>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <Link
              href={`/profile/${profile.candidate_profile_id}/edit`}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground border rounded-md px-2 py-1 hover:bg-muted transition-colors"
            >
              <Pencil size={11} />
              Edit
            </Link>
            <p className="text-xs text-muted-foreground">
              {new Date(profile.created_at).toLocaleDateString()}
            </p>
            <p className="text-xs text-muted-foreground font-mono">
              {profile.candidate_profile_id.slice(0, 12)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default async function ProfileListPage() {
  const profiles = await listProfiles().catch(() => [] as CandidateProfile[]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Candidate Profiles</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {profiles.length} profile{profiles.length !== 1 ? "s" : ""}
          </p>
        </div>
        <Link href="/profile/new">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            New Profile
          </Button>
        </Link>
      </div>

      {profiles.length === 0 ? (
        <Card>
          <CardContent className="pt-12 pb-12 text-center space-y-4">
            <UserCircle className="mx-auto text-muted-foreground" size={40} />
            <div>
              <p className="font-medium">No candidate profiles yet</p>
              <p className="text-sm text-muted-foreground mt-1">
                Create a profile to start generating Fit Reports against job roles.
              </p>
            </div>
            <Link href="/profile/new">
              <Button size="sm" className="mt-2">
                <Plus size={14} className="mr-1.5" />
                Create Profile
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {profiles.map((profile) => (
            <ProfileCard key={profile.candidate_profile_id} profile={profile} />
          ))}
        </div>
      )}

      {profiles.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground border-t pt-4">
          <Briefcase size={14} />
          <span>Open a job and click <strong>Fit Analysis</strong> to generate a match report against any profile.</span>
        </div>
      )}
    </div>
  );
}
