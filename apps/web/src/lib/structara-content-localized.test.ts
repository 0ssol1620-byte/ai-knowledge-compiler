// @vitest-environment node

import { describe, expect, it } from "vitest";

import { PUBLIC_PAGES } from "@/lib/structara-content";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";

const HANGUL = /[가-힣]/;

describe("localized public content", () => {
  it("covers every registered public page in both locales", () => {
    expect(Object.keys(PUBLIC_PAGES_KO).sort()).toEqual(
      Object.keys(PUBLIC_PAGES).sort(),
    );
    expect(Object.keys(PUBLIC_PAGES_KO)).toHaveLength(34);
  });

  it("preserves route, family, section, item, and action contracts", () => {
    for (const [path, english] of Object.entries(PUBLIC_PAGES)) {
      const korean = PUBLIC_PAGES_KO[path];
      expect(korean, `missing Korean page for ${path}`).toBeDefined();
      if (!korean) {
        throw new Error(`missing Korean page for ${path}`);
      }
      expect(korean.path).toBe(english.path);
      expect(korean.family).toBe(english.family);
      expect(korean.sections).toHaveLength(english.sections.length);
      expect(korean.primaryAction.href).toBe(english.primaryAction.href);
      expect(korean.secondaryAction?.href).toBe(english.secondaryAction?.href);

      english.sections.forEach((section, index) => {
        expect(korean.sections[index]?.items?.length ?? 0).toBe(
          section.items?.length ?? 0,
        );
      });
    }
  });

  it("contains Korean user-facing copy rather than English fallbacks", () => {
    for (const [path, page] of Object.entries(PUBLIC_PAGES_KO)) {
      const copy = [
        page.label,
        page.title,
        page.intro,
        page.thesis,
        page.primaryAction.label,
        page.secondaryAction?.label ?? "",
        ...page.sections.flatMap((section) => [
          section.title,
          section.body,
          ...(section.items ?? []),
        ]),
      ].join(" ");
      expect(HANGUL.test(copy), `${path} must contain Korean copy`).toBe(true);
    }
  });
});
