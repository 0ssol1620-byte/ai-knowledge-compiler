import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvidenceFilmStage } from "@/components/evidence-film-stage";
import { publicBenchmarkSnapshot } from "@/lib/benchmark-public";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.history.replaceState({}, "", "/");
});

describe("EvidenceFilmStage", () => {
  it("exposes all evidence scenes through real controls", () => {
    render(<EvidenceFilmStage />);
    expect(screen.getByRole("heading", { name: /One collection/ })).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "Next scene" });
    for (let index = 0; index < 4; index += 1) fireEvent.click(next);
    expect(screen.getByRole("heading", { name: /Different strengths/ })).toBeInTheDocument();
    const caseCount = publicBenchmarkSnapshot.datasets.reduce(
      (total, candidate) => total + (candidate.evidence?.case_count ?? 0),
      0,
    );
    expect(screen.getByText(`${caseCount} / ${caseCount} formal inference cases completed`)).toBeInTheDocument();
    expect(screen.getByText("$0.000676")).toBeInTheDocument();
  });

  it("has a user-controlled pause state", () => {
    render(<EvidenceFilmStage />);
    const pause = screen.getByRole("button", { name: "Pause film" });
    fireEvent.click(pause);
    expect(screen.getByRole("button", { name: "Play film" })).toBeInTheDocument();
  });

  it("holds the final brand scene for the captured film ending", async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, "", "/film?hold=1");
    render(<EvidenceFilmStage />);
    await act(() => vi.runOnlyPendingTimers());
    await act(() => vi.advanceTimersByTime(60_000));
    expect(
      screen.getByRole("heading", {
        name: "Do not organize the files. Compile the knowledge.",
      }),
    ).toBeInTheDocument();
  });
});
