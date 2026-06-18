import type { NextConfig } from "next";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Proxy /api/* and /auth/* to the FastAPI backend.
  // Browser requests hit the same Next.js origin (no CORS), and Next.js
  // forwards them server-side to FastAPI. SSR server components still call
  // FastAPI directly via the full BACKEND_URL.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/auth/:path*", destination: `${BACKEND}/auth/:path*` },
    ];
  },
  async redirects() {
    return [
      // /roles is the user-facing nav alias for the jobs catalog.
      { source: "/roles", destination: "/jobs", permanent: false },
      { source: "/roles/:path*", destination: "/jobs/:path*", permanent: false },
    ];
  },
};

export default nextConfig;
