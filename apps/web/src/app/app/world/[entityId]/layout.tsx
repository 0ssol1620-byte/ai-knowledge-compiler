"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { findWorldObject } from "@/lib/world-view-model";

const TABS = [
  { suffix: "", label: "Overview" },
  { suffix: "/source", label: "Source" },
  { suffix: "/change", label: "Change" },
  { suffix: "/ask", label: "Ask" },
] as const;

/**
 * The shared shell for one WORLD object: identity header + the SOURCE /
 * CHANGE / ASK tabs, all scoped to the same `entityId` and reading the same
 * shared `WorldProjection` from the parent `/app/world` layout.
 */
export default function WorldObjectLayout({
  children,
}: {
  children: ReactNode;
}) {
  const params = useParams<{ entityId: string }>();
  const entityId = params.entityId;
  const pathname = usePathname();
  const object = findWorldObject(entityId);
  const base = `/app/world/${entityId}`;

  return (
    <div className="world-object-page">
      <header className="world-object-header">
        <p>
          <Link href="/app/world">World</Link> / {object?.label ?? entityId}
        </p>
        <h1>{object?.label ?? "Unknown object"}</h1>
        {object && <span className="world-object-kind">{object.kind}</span>}
      </header>

      {!object ? (
        <div className="honest-state compact">
          <p>
            <code>{entityId}</code> is not an object in the sample world.
          </p>
        </div>
      ) : (
        <>
          <nav className="world-object-tabs" aria-label="Object views">
            {TABS.map((tab) => {
              const href = `${base}${tab.suffix}`;
              const active = pathname === href;
              return (
                <Link
                  key={tab.label}
                  href={href}
                  className={active ? "active" : undefined}
                  aria-current={active ? "page" : undefined}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
          <div className="world-object-tab-content">{children}</div>
        </>
      )}
    </div>
  );
}
