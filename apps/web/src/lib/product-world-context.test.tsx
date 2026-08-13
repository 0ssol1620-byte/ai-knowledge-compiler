import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoFixtureEventSource } from "@/lib/demo-event-source";
import { DEMO_COMPILE_STREAM, DEMO_TRUTH_STREAM } from "@/lib/demo-workspace";
import {
  ProductWorldProvider,
  useProductWorld,
} from "@/lib/product-world-context";

/**
 * Exercises `ProductWorldProvider` against the real `DemoFixtureEventSource`
 * at high replay speed — the same pattern `world-projection.test.ts` uses for
 * the source itself — rather than a mock, so this proves the actual seam the
 * WORLD/SOURCE/CHANGE/ASK routes depend on: the interface a source is
 * attached through, not a stand-in for it.
 */

function Probe() {
  const { projection, mode, label } = useProductWorld();
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="label">{label}</span>
      <span data-testid="entities">{projection.entityIds.length}</span>
      <span data-testid="world-active">{String(projection.worldActive)}</span>
    </div>
  );
}

function AttachProbe() {
  const { projection, attachSource } = useProductWorld();
  return (
    <div>
      <span data-testid="resolution">
        {projection.resolution?.winnerUnitId ?? "none"}
      </span>
      <button
        type="button"
        onClick={() => {
          const source = new DemoFixtureEventSource(DEMO_TRUTH_STREAM, {
            speed: 400,
          });
          attachSource(source);
        }}
      >
        resolve
      </button>
    </div>
  );
}

describe("ProductWorldProvider", () => {
  it("exposes the source's mode and label, and reduces its events", async () => {
    const source = new DemoFixtureEventSource(DEMO_COMPILE_STREAM, {
      speed: 400,
    });

    render(
      <ProductWorldProvider source={source}>
        <Probe />
      </ProductWorldProvider>,
    );

    expect(screen.getByTestId("mode").textContent).toBe("demo");
    expect(screen.getByTestId("label").textContent).toBe(
      "Sample workspace · replay",
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 120));
    });

    expect(screen.getByTestId("world-active").textContent).toBe("true");
    expect(Number(screen.getByTestId("entities").textContent)).toBeGreaterThan(
      0,
    );
  });

  it("merges a second attached source's events into the same shared projection", async () => {
    const primary = new DemoFixtureEventSource(DEMO_COMPILE_STREAM, {
      speed: 400,
    });

    render(
      <ProductWorldProvider source={primary}>
        <AttachProbe />
      </ProductWorldProvider>,
    );

    expect(screen.getByTestId("resolution").textContent).toBe("none");

    await act(async () => {
      screen.getByText("resolve").click();
      await new Promise((resolve) => setTimeout(resolve, 40));
    });

    expect(screen.getByTestId("resolution").textContent).toBe(
      "u_warranty_2026",
    );
  });
});
