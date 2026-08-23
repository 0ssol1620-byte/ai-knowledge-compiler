/**
 * The SAMPLE/LIVE data boundary — the typed contract every demo fixture must
 * cross before it reaches the screen.
 *
 * Mission §7: data that comes from a fixture is allowed in the UI only when
 * it is visibly marked as SAMPLE. Until now that rule lived in conventions —
 * a `DEMO_MODE` check here, a badge component there — and nothing stopped a
 * future edit from feeding `demoProjects` straight into a live-looking
 * surface. This module makes the boundary a type instead:
 *
 *     fixture ──▶ asSample() ──▶ SampleMarked<T> ──▶ UI (badge rendered)
 *     backend ──▶ asLive()  ──▶ LiveMarked<T>   ──▶ UI (no badge)
 *
 * `SampleMarked<T>` carries a phantom brand key (`sampleMark`) that is NOT
 * exported, so an object literal cannot satisfy it — the ONLY constructor of
 * sample-marked data in the codebase is `asSample`, and `asSample` attaches
 * the `{ label: "SAMPLE" }` badge unconditionally. There is no overload, no
 * option, and no second entry point that produces sample data without the
 * badge: the mark and the badge are the same object.
 *
 * Surfaces read the envelope with `isLive`/`isSample` and render the badge
 * from `marked.badge.label` (see components/data/sample-data-badge.tsx for
 * the generic renderer; the WORLD namespace keeps its richer
 * SampleWorldBadge). Passing `marked.data` onward without rendering the badge
 * is still physically possible — TypeScript cannot see JSX — but the marked
 * envelope makes every such hand-off grep-able (`.data` off a `SampleMarked`)
 * and reviewable, which is the strongest contract a compile step can offer.
 *
 * Nothing here fabricates live data: `asLive` is called only on payloads an
 * actual `/v1/...` response produced. When the backend is unreachable the
 * world client stubs fall back to `asSample(fixture)` — honestly labelled,
 * never dressed up as live.
 */

/** Which side of the boundary a payload came from. */
export type DataSource = "sample" | "live";

/**
 * The badge every sample payload is required to render. The label is a
 * literal, not a string: a typo'd or renamed badge fails to compile.
 */
export interface SampleBadge {
  readonly label: "SAMPLE";
}

export const SAMPLE_BADGE_LABEL: SampleBadge["label"] = "SAMPLE";

/**
 * Phantom brand key. Declared but never exported, so only this module can
 * name it and only `asSample` can produce a value that has it.
 */
declare const sampleMark: unique symbol;

/**
 * Fixture data wrapped for the UI. Constructible only via {@link asSample};
 * the badge travels with the data everywhere it goes.
 */
export interface SampleMarked<T> {
  readonly source: Extract<DataSource, "sample">;
  readonly badge: SampleBadge;
  readonly data: T;
  readonly [sampleMark]: true;
}

/** Live backend data wrapped for the UI. No badge — none is allowed. */
export interface LiveMarked<T> {
  readonly source: Extract<DataSource, "live">;
  readonly data: T;
}

/** Either side of the boundary, as the client stubs return it. */
export type MarkedData<T> = SampleMarked<T> | LiveMarked<T>;

/**
 * Mark fixture data as SAMPLE. The badge is attached here, unconditionally —
 * this is the "배지 강제" point of the whole module: there is no way to obtain
 * `SampleMarked<T>` without also obtaining its SAMPLE badge.
 *
 * The returned envelope is frozen so a caller cannot strip the badge and pass
 * the remainder around as if the marking never happened.
 */
export function asSample<T>(data: T): SampleMarked<T> {
  return Object.freeze({
    source: "sample",
    badge: Object.freeze({ label: SAMPLE_BADGE_LABEL }),
    data,
  }) as SampleMarked<T>;
}

/**
 * Wrap a real backend response. Exists so client functions have a symmetric
 * return shape (`MarkedData<T>`) — it confers no badge and must never be
 * handed fixture content.
 */
export function asLive<T>(data: T): LiveMarked<T> {
  return { source: "live", data };
}

/** Narrow to the live branch. */
export function isLive<T>(value: MarkedData<T>): value is LiveMarked<T> {
  return value.source === "live";
}

/** Narrow to the sample branch (the one that owes the badge). */
export function isSample<T>(value: MarkedData<T>): value is SampleMarked<T> {
  return value.source === "sample";
}

/** Which side of the boundary a payload came from, as data. */
export function dataSourceOf<T>(value: MarkedData<T>): DataSource {
  return value.source;
}

/** Read the payload back out of either envelope. */
export function markedValue<T>(value: MarkedData<T>): T {
  return value.data;
}
