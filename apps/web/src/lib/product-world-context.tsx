"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { ProductEvent, ProductEventSource } from "@/lib/product-event";
import {
  EMPTY_PROJECTION,
  reduceProductEvent,
  type WorldProjection,
} from "@/lib/world-projection";

/**
 * The one place a WORLD/SOURCE/CHANGE/ASK component reads world state from.
 *
 * Every component below this provider is written against `WorldProjection`
 * and the `mode`/`label` it carries — never against a concrete
 * `ProductEventSource` implementation. `DemoFixtureEventSource` is the only
 * implementation that exists today (see lib/demo-world-source.ts, the one
 * place that names it); a future `LiveProductEventSource` satisfies the same
 * `ProductEventSource` interface and swaps in there without this provider,
 * or anything downstream of it, changing.
 */
export interface ProductWorldContextValue {
  projection: WorldProjection;
  mode: "demo" | "live";
  label: string;
  /**
   * Feed a second, short-lived source's events into the same shared
   * projection — used by the CHANGE and ASK views to replay a scoped
   * follow-up stream (a source revision, a question) without discarding the
   * WORLD state already built up. Returns a stop function; the source is
   * also stopped automatically on unmount.
   */
  attachSource: (source: ProductEventSource) => () => void;
}

const ProductWorldContext = createContext<ProductWorldContextValue | undefined>(
  undefined,
);

export function ProductWorldProvider({
  source,
  children,
}: {
  source: ProductEventSource;
  children: ReactNode;
}) {
  const [projection, setProjection] = useState<WorldProjection>(EMPTY_PROJECTION);

  const attachSource = useCallback((attached: ProductEventSource) => {
    const unsubscribe = attached.subscribe((event: ProductEvent) => {
      setProjection((previous) => reduceProductEvent(previous, event));
    });
    attached.start();
    return () => {
      unsubscribe();
      attached.stop();
    };
  }, []);

  useEffect(() => {
    const detach = attachSource(source);
    return detach;
    // `source` is expected to be stable for the lifetime of the provider
    // (created once via useMemo by the caller); re-running this effect on an
    // unstable reference would restart the primary world stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const value = useMemo<ProductWorldContextValue>(
    () => ({ projection, mode: source.mode, label: source.label, attachSource }),
    [projection, source, attachSource],
  );

  return (
    <ProductWorldContext.Provider value={value}>
      {children}
    </ProductWorldContext.Provider>
  );
}

export function useProductWorld(): ProductWorldContextValue {
  const context = useContext(ProductWorldContext);
  if (!context) {
    throw new Error("useProductWorld must be used within a ProductWorldProvider");
  }
  return context;
}
