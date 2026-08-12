import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeFlow } from "@/components/marketing/knowledge-flow";
import { ProductFilmDialog } from "@/components/marketing/product-film-dialog";
import { RawCompiledCompare } from "@/components/marketing/raw-compiled-compare";

class IntersectionObserverProbe {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", IntersectionObserverProbe);
  HTMLDialogElement.prototype.showModal = vi.fn(function showModal(
    this: HTMLDialogElement,
  ) {
    this.setAttribute("open", "");
  });
  HTMLDialogElement.prototype.close = vi.fn(function close(
    this: HTMLDialogElement,
  ) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("reference-integrated marketing interactions", () => {
  it("keeps the compare control operable by range input, buttons, and keyboard", () => {
    render(<RawCompiledCompare locale="ko" />);
    const slider = screen.getByRole("slider", { name: "비교 경계" });

    fireEvent.change(slider, { target: { value: "76" } });
    expect(slider).toHaveValue("76");

    fireEvent.click(screen.getByRole("button", { name: "결과" }));
    expect(slider).toHaveValue("0");

    fireEvent.keyDown(slider, { key: " " });
    expect(slider).toHaveValue("50");
  });

  it("provides the animated provenance diagram as an ordered text alternative", () => {
    render(<KnowledgeFlow locale="en" />);

    expect(screen.getByText("Inputs: PDF, Office, Images, URL")).toBeVisible();
    expect(
      screen.getByText("Compiler: Structure, Verify, Connect"),
    ).toBeVisible();
    expect(
      screen.getByText("Outputs: Markdown, Obsidian, Graph, RAG"),
    ).toBeVisible();
  });

  it("opens the measured film in a native modal without autoplay", () => {
    render(<ProductFilmDialog locale="en" />);

    fireEvent.click(
      screen.getAllByRole("button", {
        name: /Play the 60-second film/,
      })[0]!,
    );

    const dialog = screen.getByRole("dialog", {
      name: "Evidence in Motion product film",
    });
    expect(dialog).toHaveAttribute("open");
    expect(dialog.querySelector("video")).not.toHaveAttribute("autoplay");
  });
});
