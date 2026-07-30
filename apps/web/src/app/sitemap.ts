import type { MetadataRoute } from "next";

import { PUBLIC_PAGES } from "@/lib/structara-content";

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://127.0.0.1:3000";
  const paths = ["/", ...Object.keys(PUBLIC_PAGES)];
  return paths.map((path) => ({
    url: new URL(path, siteUrl).toString(),
    changeFrequency:
      path === "/" || path === "/research" || path.includes("changelog")
        ? "weekly"
        : "monthly",
    priority: path === "/" ? 1 : path.startsWith("/product") ? 0.9 : 0.7,
  }));
}
