import type { WorkspaceDashboardSnapshot } from "@/components/workspace-dashboard";
import { demoProjects } from "@/lib/demo-data";

export const demoWorkspaceSnapshot: WorkspaceDashboardSnapshot = {
  active_project_count: 3,
  active_jobs: 1,
  review_required: 7,
  failed_jobs: 0,
  processed_pages_this_cycle: 1284,
  storage_used_bytes: 842 * 1024 * 1024,
  credit_remaining: 2140,
  retention_days: 7,
  provenance_coverage: 0.992,
  external_pages: 0,
  projects: demoProjects.map((project, index) => ({
    ...project,
    owner_name: index === 0 ? "Demo Kim" : "Sample team",
  })),
};
