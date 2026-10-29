import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Production: static export served by FastAPI. Dev: proxy /api to the backend.
  ...(isDev ? {} : { output: "export" as const }),
  images: { unoptimized: true },
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }
    : {}),
};

export default nextConfig;
