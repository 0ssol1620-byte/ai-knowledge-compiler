import { expect, test } from "@playwright/test";

/**
 * §20 [확정] — the four responsive bands, asserted against the table.
 *
 * §20 sets three boundaries (1280 / 1024 / 768) and four bands, and the bands
 * are a specification rather than a suggestion: the facing spread holds at 5:7
 * above 1280, narrows to 6:6 through 1024-1279, and goes vertical below 1024.
 *
 * This is checked in a browser rather than by reading media queries because
 * the failure it exists to catch was invisible in the source. The rules used
 * max-width, every boundary landed one pixel inside the wrong band, and the
 * spread held down to 768 — so 900px showed two columns where the table says
 * one. Nothing about the CSS looked wrong; only the rendered layout did.
 */

const BANDS = [
  { width: 1440, tracks: 2, ratio: 5 / 7, note: ">= 1280 — facing spread at 5:7" },
  { width: 1280, tracks: 2, ratio: 5 / 7, note: "the 1280 boundary belongs to the 5:7 band" },
  { width: 1024, tracks: 2, ratio: 1, note: "1024-1279 — spread held, but 6:6" },
  { width: 900, tracks: 1, ratio: null, note: "768-1023 — vertical" },
  { width: 768, tracks: 1, ratio: null, note: "the 768 boundary belongs to the vertical band" },
  { width: 390, tracks: 1, ratio: null, note: "<= 767 — vertical" },
] as const;

for (const band of BANDS) {
  test(`hero at ${band.width}px: ${band.note}`, async ({ page }) => {
    await page.setViewportSize({ width: band.width, height: 900 });
    await page.goto("/design/hero");

    const columns = await page.evaluate(() => {
      const hero = document.querySelector(".tv-hero-comp");
      return hero ? getComputedStyle(hero).gridTemplateColumns : null;
    });
    expect(columns, "the hero comp should be on the page").not.toBeNull();

    // getComputedStyle returns used values with units — "520px 728px".
    const tracks = columns!
      .split(/\s+/)
      .filter(Boolean)
      .map((track) => Number.parseFloat(track));
    expect(tracks).toHaveLength(band.tracks);

    if (band.ratio !== null) {
      // Tolerance covers sub-pixel track sizing, not a different ratio: 5:7 is
      // 0.714 and 6:6 is 1.0, so the two cannot be confused at this precision.
      expect(tracks[0]! / tracks[1]!).toBeCloseTo(band.ratio, 2);
    }
  });
}
