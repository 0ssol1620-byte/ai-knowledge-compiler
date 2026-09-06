import type { MetadataRoute } from "next";

import { PUBLIC_PAGES } from "@/lib/tavonel-content";

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://127.0.0.1:3000";
  const hidden = new Set(["/customers", "/benchmarks", "/research/experiments"]);
  const paths = ["/", ...Object.keys(PUBLIC_PAGES).filter((path) => !hidden.has(path))];
  return paths.map((path) => ({
    url: new URL(path, siteUrl).toString(),
    changeFrequency:
      path === "/" || path === "/research" || path.includes("changelog")
        ? "weekly"
        : "monthly",
    priority: path === "/" ? 1 : path.startsWith("/product") ? 0.9 : 0.7,
  }));
}
