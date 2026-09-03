import type { Metadata } from "next";
import { notFound } from "next/navigation";


export const metadata: Metadata = {
  title: "Document benchmarks",
  description:
    "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
  robots: { index: false, follow: false },
};

export default function BenchmarksPage() {
  notFound();
}
