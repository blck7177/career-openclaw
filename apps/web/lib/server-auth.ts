/**
 * Server-only authentication helpers for Next.js Server Components.
 *
 * This file is intentionally SEPARATE from api.ts because it imports
 * "next/headers", a server-only module that Turbopack will reject if it ends
 * up in any Client Component bundle (even via dynamic import).
 *
 * ── Development ──────────────────────────────────────────────────────────────
 * api.ts already adds X-Dev-Context: "dev" to every request, so the FastAPI
 * DEV_MODE bypass handles auth for all SSR fetches. serverAuthHeaders()
 * returns {} in development, so you can safely call it without side effects.
 *
 * ── Production SSR ───────────────────────────────────────────────────────────
 * Browser session cookies are NOT automatically forwarded by Next.js when a
 * Server Component fetches from the FastAPI backend. This function reads the
 * incoming request's "sid" cookie and returns a Cookie header so the backend
 * receives it.
 *
 * Usage in a Server Component page:
 *
 *   import { serverAuthHeaders } from "@/lib/server-auth";
 *   import { listJobs } from "@/lib/api";
 *
 *   export default async function Page() {
 *     const sah = await serverAuthHeaders();
 *     const jobs = await fetch(`${BASE}/api/jobs`, {
 *       credentials: "include",
 *       headers: { ...sah },
 *     });
 *     // …
 *   }
 *
 * Or pass `sah` into any api.ts function that accepts an `extraHeaders`
 * parameter (add that parameter when upgrading to production).
 */

import { cookies } from "next/headers";

export async function serverAuthHeaders(): Promise<Record<string, string>> {
  // In development, api.ts already handles auth via X-Dev-Context.
  if (process.env.NODE_ENV === "development") return {};

  try {
    const cookieStore = await cookies();
    const sid = cookieStore.get("sid")?.value;
    return sid ? { Cookie: `sid=${sid}` } : {};
  } catch {
    // Not inside a Server Component context (e.g. static generation, tests).
    return {};
  }
}
