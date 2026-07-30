import type { Metadata } from "next";

import { BenchmarkLab } from "@/components/benchmark-lab";

export const metadata: Metadata = { title: "Benchmarks" };

export default function BenchmarksPage() {
  return <BenchmarkLab />;
}
