import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://127.0.0.1:3000";
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/app/",
        "/documents/",
        "/login",
        "/signup",
        "/onboarding",
        "/forgot-password",
        "/sso",
      ],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
