import type { Metadata } from "next";

import { EvidenceFilmStage } from "@/components/evidence-film-stage";

export const metadata: Metadata = {
  title: "Evidence in Motion | Structara",
  description: "A measured 60-second product film showing documents becoming verified, portable knowledge.",
};

export default function FilmPage() {
  return <EvidenceFilmStage />;
}
