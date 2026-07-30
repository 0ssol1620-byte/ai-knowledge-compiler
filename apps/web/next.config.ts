import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  typedRoutes: true,
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    webpackBuildWorker: false,
  },
  webpack(config, { dev }) {
    if (!dev) config.cache = false;
    // react-spline 4.1 publishes ESM-only `import` conditions. Next's
    // webpack resolver on Windows does not currently select that condition
    // for a client-only dynamic import, so point the exact public subpath at
    // the package's published Next.js entry.
    config.resolve.alias["@splinetool/react-spline/next$"] = path.join(
      process.cwd(),
      "node_modules",
      "@splinetool",
      "react-spline",
      "dist",
      "react-spline-next.js",
    );
    return config;
  },
  // CI runs `tsc --noEmit` as a separate strict gate. The Next.js Windows
  // type-check worker can deadlock after compilation, so the build does not
  // invoke that duplicate worker.
  typescript: {
    ignoreBuildErrors: true,
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value:
              "camera=(), microphone=(), geolocation=(), browsing-topics=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
