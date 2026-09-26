import type { Metadata } from "next";

import { EvidenceFilmStage } from "@/components/evidence-film-stage";
import "@/styles/evidence-film.css";

export const metadata: Metadata = {
  title: "Evidence in Motion | TAVONEL",
  description: "A measured 60-second product film showing documents becoming verified, portable knowledge.",
};

export default function FilmPage() {
  return <EvidenceFilmStage />;
}
