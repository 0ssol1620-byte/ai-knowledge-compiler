import type { MetadataRoute } from "next";

import { PUBLIC_BRAND } from "@/lib/brand";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${PUBLIC_BRAND.name} — ${PUBLIC_BRAND.category}`,
    short_name: PUBLIC_BRAND.name,
    description:
      "Compile documents into structured, verified, connected, portable knowledge.",
    start_url: "/",
    display: "standalone",
    background_color: "#F5F3EE",
    theme_color: "#101216",
    lang: "en",
  };
}
