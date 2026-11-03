import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// Production: static export served by FastAPI on the same origin.
// Development (`npm run dev`): proxy /api to a backend running on :8000.
const nextConfig: NextConfig = isDev
  ? {
      async rewrites() {
        return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
      },
    }
  : {
      output: "export",
      images: { unoptimized: true },
    };

export default nextConfig;
