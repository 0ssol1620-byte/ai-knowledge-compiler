import type { Metadata } from "next";

import { ApiWorkflowStudio } from "@/components/api-workflow-studio";

export const metadata: Metadata = { title: "API & workflows" };

export default function ApiWorkflowsPage() {
  return <ApiWorkflowStudio />;
}
