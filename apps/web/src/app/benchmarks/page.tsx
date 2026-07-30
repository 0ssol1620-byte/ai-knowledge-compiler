import type { Metadata } from "next";

import { BenchmarkLab } from "@/components/benchmark-lab";

export const metadata: Metadata = { title: "벤치마크" };

export default function BenchmarksPage() {
  return <BenchmarkLab />;
}
