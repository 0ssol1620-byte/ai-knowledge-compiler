import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  typedRoutes: true,
  allowedDevOrigins: ["127.0.0.1"],
  // §22 — without these the 2880×1800 hero master can reach the browser at
  // full size. deviceSizes matches the §20 breakpoints (1280 · 1024 · 768)
  // plus the capture widths the QA evidence uses.
  images: {
    formats: ["image/avif", "image/webp"],
    deviceSizes: [360, 390, 768, 1024, 1280, 1440, 1920],
    imageSizes: [16, 24, 32, 48, 64, 96, 128, 256, 384],
    minimumCacheTTL: 60 * 60 * 24 * 30,
    dangerouslyAllowSVG: false,
  },
  experimental: {
    webpackBuildWorker: false,
  },
  webpack(config, { dev }) {
    if (!dev) config.cache = false;
    return config;
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
