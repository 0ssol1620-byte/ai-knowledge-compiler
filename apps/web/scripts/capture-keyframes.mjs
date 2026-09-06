/**
 * Capture the cinematic as stills at the canonical artboard.
 *
 * Two surfaces, two purposes:
 *
 *   - `/experience/keyframes` — the §20.1 founder-approval gate frames.
 *   - `/experience/board` — all 24 beats of the §5.3 board, which is how a
 *     beat that draws nothing or repeats its neighbour gets caught. Motion
 *     hides both.
 *
 * Everything is shot at exactly 1440x900 so a pixel in the file is a canonical
 * pixel and a spec coordinate can be checked literally.
 *
 *   node scripts/capture-keyframes.mjs [baseUrl] [outDir]
 */

import { mkdir } from "node:fs/promises";
import path from "node:path";

import { chromium } from "@playwright/test";

const BASE_URL = process.argv[2] ?? "http://localhost:3000";
const OUT_DIR = process.argv[3] ?? "keyframe-captures";

/** Hides dev-server chrome that otherwise lands inside the frame. */
const PIN_ARTBOARD = `
  section div[style*="aspect-ratio"] { width: 1440px !important; }
  nextjs-portal, #__next-build-watcher { display: none !important; }
`;

const browser = await chromium.launch();
try {
  await mkdir(OUT_DIR, { recursive: true });

  for (const reducedMotion of ["no-preference", "reduce"]) {
    const suffix = reducedMotion === "reduce" ? ".reduced" : "";
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 2,
      reducedMotion,
    });
    const page = await context.newPage();

    // ── Gate frames ────────────────────────────────────────────────────────
    await page.goto(`${BASE_URL}/experience/keyframes`, {
      waitUntil: "networkidle",
    });
    await page.addStyleTag({ content: PIN_ARTBOARD });
    await page.waitForTimeout(400);

    const gateSections = page.locator("main > div > section");
    const gateCount = await gateSections.count();
    if (gateCount === 0) {
      throw new Error("The keyframe review page rendered no scenes.");
    }
    for (let i = 0; i < gateCount; i += 1) {
      const stages = gateSections.nth(i).locator('div[style*="aspect-ratio"]');
      const n = await stages.count();
      for (let j = 0; j < n; j += 1) {
        const file = path.join(OUT_DIR, `gate-${i + 1}.${j + 1}${suffix}.png`);
        await stages.nth(j).screenshot({ path: file });
        process.stdout.write(`captured ${file}\n`);
      }
    }

    // ── The full board ─────────────────────────────────────────────────────
    await page.goto(`${BASE_URL}/experience/board`, { waitUntil: "networkidle" });
    await page.addStyleTag({ content: PIN_ARTBOARD });
    await page.waitForTimeout(400);

    const beats = page.locator("section[data-shot]");
    const beatCount = await beats.count();
    if (beatCount !== 24) {
      throw new Error(
        `Expected 24 beats on the board, found ${beatCount}. The board page ` +
          `and the shot manifest have drifted apart.`,
      );
    }
    for (let i = 0; i < beatCount; i += 1) {
      const section = beats.nth(i);
      const id = await section.getAttribute("data-shot");
      const file = path.join(OUT_DIR, `board-${id}${suffix}.png`);
      await section.locator('div[style*="aspect-ratio"]').screenshot({ path: file });
      process.stdout.write(`captured ${file}\n`);
    }

    await context.close();
  }
} finally {
  await browser.close();
}
