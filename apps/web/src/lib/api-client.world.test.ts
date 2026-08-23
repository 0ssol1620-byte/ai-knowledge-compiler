import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ask,
  getWorld,
  isLive,
  isSample,
  listChanges,
} from "@/lib/api-client";
import {
  DEMO_ANSWER,
  DEMO_ENTITIES,
  DEMO_GUARANTEES,
  DEMO_RELATIONS,
  DEMO_TRACE,
  DEMO_WORLD_STATE_ID,
} from "@/lib/demo-workspace";

/**
 * The /v1/world client stubs are exercised against a stubbed global fetch:
 * a responding backend must come back live-marked, and every failure path
 * must fall back to sample-marked fixture data (never to invented "live"
 * content).
 */
function stubFetchOnce(payload: unknown, status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValueOnce(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function breakFetchOnce(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getWorld", () => {
  it("returns live-marked state when the backend responds", async () => {
    const state = {
      id: "ws_live_1",
      revision: 4,
      entity_count: 99,
      relation_count: 120,
    };
    stubFetchOnce(state);

    const result = await getWorld("ws_live_1");

    expect(isLive(result)).toBe(true);
    if (!isLive(result)) throw new Error("expected live-marked data");
    expect(result.data).toEqual(state);
    expect("badge" in result).toBe(false);
  });

  it("falls back to SAMPLE-marked fixture state when the backend is unreachable", async () => {
    breakFetchOnce();

    const result = await getWorld(DEMO_WORLD_STATE_ID);

    expect(isSample(result)).toBe(true);
    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.badge.label).toBe("SAMPLE");
    expect(result.data.id).toBe(DEMO_WORLD_STATE_ID);
    expect(result.data.revision).toBe(1);
    expect(result.data.entity_count).toBe(DEMO_ENTITIES.length);
    expect(result.data.relation_count).toBe(DEMO_RELATIONS.length);
  });

  it("falls back to the fixture world id rather than echoing an unknown id as resolved", async () => {
    breakFetchOnce();

    const result = await getWorld("ws_does_not_exist");

    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.data.id).toBe(DEMO_WORLD_STATE_ID);
  });
});

describe("listChanges", () => {
  it("returns live-marked changes when the backend responds", async () => {
    stubFetchOnce([
      { id: "chg_live_1", world_state_id: "ws_live_1", summary: "s", changed_at: "2026-08-20T00:00:00.000Z" },
    ]);

    const result = await listChanges("2026-08-19T00:00:00.000Z");

    expect(isLive(result)).toBe(true);
  });

  it("falls back to the fixture change for a cursor before the fixture epoch", async () => {
    breakFetchOnce();

    const result = await listChanges("2026-08-01T00:00:00.000Z");

    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.badge.label).toBe("SAMPLE");
    expect(result.data).toHaveLength(1);
    expect(result.data[0]?.changed_at).toBe("2026-08-11T09:00:00.000Z");
  });

  it("falls back to an empty SAMPLE list once the cursor passes the fixture epoch", async () => {
    breakFetchOnce();

    const result = await listChanges("2026-08-12T00:00:00.000Z");

    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.data).toEqual([]);
  });

  it("treats an unparseable cursor as 'from the beginning' on the sample path", async () => {
    breakFetchOnce();

    const result = await listChanges("not-a-timestamp");

    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.data).toHaveLength(1);
  });
});

describe("ask", () => {
  it("returns live-marked answers when the backend responds", async () => {
    stubFetchOnce({
      question: "What is the current warranty?",
      answer: "5 years",
      guarantees: [],
      trace: [],
    });

    const result = await ask("What is the current warranty?");

    expect(isLive(result)).toBe(true);
  });

  it("posts the query to /v1/world/ask before falling back", async () => {
    const fetchMock = stubFetchOnce({});

    await ask("anything").catch(() => undefined);

    // Response body {} parses fine, so this only checks the request shape;
    // the failure-path shape is covered by the next test.
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/v1/world/ask");
    expect((init as RequestInit | undefined)?.method).toBe("POST");
  });

  it("falls back to the SAMPLE fixture exchange when the backend fails", async () => {
    breakFetchOnce();

    const result = await ask("What is the current warranty?");

    if (!isSample(result)) throw new Error("expected sample-marked fallback");
    expect(result.badge.label).toBe("SAMPLE");
    expect(result.data.question).toBe("What is the current warranty?");
    expect(result.data.answer).toBe(DEMO_ANSWER);
    expect(result.data.guarantees).toEqual(DEMO_GUARANTEES);
    expect(result.data.trace).toEqual(DEMO_TRACE);
  });
});
