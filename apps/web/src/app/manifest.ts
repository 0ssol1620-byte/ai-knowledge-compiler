import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Structara — The Knowledge Compiler for AI",
    short_name: "Structara",
    description:
      "Compile documents into structured, verified, connected, portable knowledge.",
    start_url: "/",
    display: "standalone",
    background_color: "#F5F3EE",
    theme_color: "#101216",
    lang: "en",
  };
}
