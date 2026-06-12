import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow the app to call the local FastAPI backend during SSR in dev
  // (no need for CORS workarounds since we use credentials: "include")
  experimental: {
    // Required for server components fetching from localhost
  },
};

export default nextConfig;
