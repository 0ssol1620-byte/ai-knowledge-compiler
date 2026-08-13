import { describe, expect, it } from "vitest";

import {
  DEMO_COMPILE_STREAM,
  DEMO_ENTITIES,
  DEMO_RELATIONS,
  DEMO_UNITS,
} from "@/lib/demo-workspace";
import { reduceProductEvents } from "@/lib/world-projection";
import {
  askEligible,
  changeEligible,
  findWorldObject,
  relatedObjects,
  sourceUnitsForEntity,
  worldObjects,
} from "@/lib/world-view-model";

const compiledProjection = reduceProductEvents(
  DEMO_COMPILE_STREAM.map((scheduled) => scheduled.event),
);

describe("worldObjects", () => {
  it("returns nothing outside sample mode, even with entities present", () => {
    expect(worldObjects(compiledProjection, "live")).toEqual([]);
    expect(worldObjects(compiledProjection, "idle")).toEqual([]);
  });

  it("lists every compiled entity in demo mode, with its relation count", () => {
    const objects = worldObjects(compiledProjection, "demo");
    expect(objects).toHaveLength(DEMO_ENTITIES.length);
    const warranty = objects.find((o) => o.id === "e_policy_warranty");
    expect(warranty?.label).toBe("Warranty Policy");
    const expectedRelations = DEMO_RELATIONS.filter(
      (r) => r.from === "e_policy_warranty" || r.to === "e_policy_warranty",
    ).length;
    expect(warranty?.relationCount).toBe(expectedRelations);
  });

  it("only lists entities the projection has actually resolved", () => {
    const partial = reduceProductEvents(
      DEMO_COMPILE_STREAM.map((s) => s.event).slice(0, 5),
    );
    expect(worldObjects(partial, "demo")).toEqual([]);
  });
});

describe("findWorldObject", () => {
  it("finds a known entity", () => {
    expect(findWorldObject("e_customer_a")?.label).toBe("Customer A");
  });

  it("returns undefined for an unknown id", () => {
    expect(findWorldObject("e_does_not_exist")).toBeUndefined();
  });
});

describe("relatedObjects", () => {
  it("resolves both directions of a relation with a readable label", () => {
    const related = relatedObjects("e_policy_warranty");
    const toKorea = related.find((r) => r.otherId === "e_region_kr");
    expect(toKorea).toMatchObject({
      predicate: "applies in",
      direction: "from",
      otherLabel: "Korea",
    });
    const fromProduct = related.find((r) => r.otherId === "e_product_x");
    expect(fromProduct).toMatchObject({
      predicate: "governed by",
      direction: "to",
      otherLabel: "Product X",
    });
  });

  it("returns an empty list for an object with no relations", () => {
    expect(relatedObjects("e_does_not_exist")).toEqual([]);
  });
});

describe("sourceUnitsForEntity", () => {
  it("resolves a document entity to the unit sourced from it", () => {
    const units = sourceUnitsForEntity("e_doc_policy_2026");
    expect(units).toHaveLength(1);
    expect(units[0]?.id).toBe("u_warranty_2026");
  });

  it("resolves the subject policy entity to every unit about it", () => {
    const units = sourceUnitsForEntity("e_policy_warranty");
    expect(units.map((u) => u.id).sort()).toEqual(
      [...DEMO_UNITS.map((u) => u.id)].sort(),
    );
  });

  it("honestly returns nothing for an object with no modeled evidence", () => {
    expect(sourceUnitsForEntity("e_region_jp")).toEqual([]);
  });
});

describe("changeEligible", () => {
  it("is true only for the warranty policy entity", () => {
    expect(changeEligible("e_policy_warranty")).toBe(true);
    expect(changeEligible("e_region_jp")).toBe(false);
    expect(changeEligible("e_customer_a")).toBe(false);
  });
});

describe("askEligible", () => {
  it("is true for every entity on the sample's relation spine", () => {
    for (const id of [
      "e_customer_a",
      "e_contract_182",
      "e_product_x",
      "e_policy_warranty",
      "e_region_kr",
    ]) {
      expect(askEligible(id)).toBe(true);
    }
  });

  it("is false for an entity off the spine", () => {
    expect(askEligible("e_region_jp")).toBe(false);
    expect(askEligible("e_distributor_kr")).toBe(false);
  });
});
