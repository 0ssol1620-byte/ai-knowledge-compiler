import type { Metadata } from "next";

import { ApiWorkflowStudio } from "@/components/api-workflow-studio";

export const metadata: Metadata = { title: "API & 워크플로" };

export default function ApiWorkflowsPage() {
  return <ApiWorkflowStudio />;
}
