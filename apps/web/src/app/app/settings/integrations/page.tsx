import type { Metadata } from "next";

import { ConnectionsCatalog } from "@/components/connections-catalog";

export const metadata: Metadata = {
  title: "Connections",
  description: "Executable TAVONEL source paths and their current operating state.",
  robots: { index: false, follow: false },
};

export default function ConnectionsPage() {
  return <ConnectionsCatalog />;
}
