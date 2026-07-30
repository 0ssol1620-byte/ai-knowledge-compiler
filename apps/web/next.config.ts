import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
