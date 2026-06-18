import { getProfile } from "@/lib/api";
import { notFound } from "next/navigation";
import EditProfileForm from "./EditProfileForm";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ profile_id: string }>;
}

export default async function EditProfilePage({ params }: PageProps) {
  const { profile_id } = await params;
  const profile = await getProfile(profile_id).catch(() => null);

  if (!profile) {
    notFound();
  }

  return <EditProfileForm profile={profile} />;
}
