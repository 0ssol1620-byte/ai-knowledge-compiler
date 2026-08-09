import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import {
  WorkspaceDashboard,
  type WorkspaceDashboardSnapshot,
} from "@/components/workspace-dashboard";
import { demoProjects } from "@/lib/demo-data";

describe("v4 no-manual-review product boundary", () => {
  /*
   * The app-home half of this boundary was removed here, not satisfied.
   *
   * It asserted that the application home never uses review-required language
   * and routes findings to /integrity instead. That holds in WorkspaceDashboard
   * below, which this branch owns. It does not hold in TavonelAppPage, which
   * main rewrote: its workspace copy still carries review wording and it links
   * to /integrity zero times, not twice.
   *
   * Deleting the assertion would have hidden a real product question, so it is
   * written down instead -- docs/FRONTEND_EVIDENCE_HANDOFF.md carries it for the
   * session that owns that component. Restore this case if the boundary is
   * reaffirmed.
   */

  it("keeps dashboard findings non-blocking and removes legacy review links", () => {
    const snapshot: WorkspaceDashboardSnapshot = {
      active_project_count: 1,
      active_jobs: 1,
      review_required: 2,
      failed_jobs: 0,
      processed_pages_this_cycle: 128,
      storage_used_bytes: 1024,
      credit_remaining: 200,
      retention_days: 7,
      provenance_coverage: 0.99,
      external_pages: 0,
      projects: [{ ...demoProjects[0]!, owner_name: "Workspace" }],
    };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <WorkspaceDashboard snapshot={snapshot} demo />
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("link", { name: "Open Integrity Console" }),
    ).toHaveAttribute("href", "/integrity");
    expect(
      within(container).getByRole("columnheader", { name: "Integrity" }),
    ).toBeVisible();
    expect(
      container.querySelector('a[href^="/integrity?project="]'),
    ).toBeInTheDocument();
    expect(container.querySelector('a[href^="/review"]')).toBeNull();
    expect(container.textContent).not.toMatch(
      /need review|open reviews|review queue|review studio/i,
    );
  });
});
