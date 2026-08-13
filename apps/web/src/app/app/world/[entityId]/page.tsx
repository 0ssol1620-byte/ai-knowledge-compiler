"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { relatedObjects } from "@/lib/world-view-model";

/** Overview — this object's direct connections in the world graph. */
export default function WorldObjectOverviewPage() {
  const params = useParams<{ entityId: string }>();
  const related = relatedObjects(params.entityId);

  if (related.length === 0) {
    return (
      <div className="honest-state compact">
        <p>This object has no recorded connections in the sample world.</p>
      </div>
    );
  }

  return (
    <ul className="world-relation-list">
      {related.map((relation) => (
        <li key={relation.relationId}>
          {relation.direction === "from" ? (
            <span>
              <strong>this object</strong> {relation.predicate}{" "}
              <Link href={`/app/world/${relation.otherId}`}>
                {relation.otherLabel}
              </Link>
            </span>
          ) : (
            <span>
              <Link href={`/app/world/${relation.otherId}`}>
                {relation.otherLabel}
              </Link>{" "}
              {relation.predicate} <strong>this object</strong>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
