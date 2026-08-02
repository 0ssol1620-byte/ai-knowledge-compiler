import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseUrl = process.env.STRUCTARA_CAPTURE_URL ?? "http://127.0.0.1:3000";
const outputDirectory = path.resolve("artifacts/reference-ui");
const targets = [
  [".st-home-hero", "hero"],
  [".st-reference-compare", "compare"],
  ["#transformation", "transformation"],
  [".st-live-product-section", "live-product"],
  [".st-knowledge-flow", "knowledge-flow"],
  [".st-product-film-dialog", "product-film"],
];

await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
  colorScheme: "light",
  reducedMotion: "no-preference",
});

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForTimeout(2_500);
  for (const [selector, name] of targets) {
    const target = page.locator(selector);
    await target.scrollIntoViewIfNeeded();
    await page.waitForTimeout(450);
    await target.screenshot({
      path: path.join(outputDirectory, `${name}-1440.webp`),
      animations: "disabled",
    });
  }
  const compareControlStyles = await page
    .locator(".st-compare-actions button")
    .first()
    .evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        minWidth: style.minWidth,
        minHeight: style.minHeight,
        padding: style.padding,
        border: style.border,
        background: style.backgroundColor,
      };
    });
  const heroMetaFontSize = await page
    .locator(".st-hero-scene-meta small")
    .evaluate((element) => getComputedStyle(element).fontSize);
  const storyMicrocopyFontSize = await page
    .locator(".st-story-scene > div small")
    .first()
    .evaluate((element) => getComputedStyle(element).fontSize);
  console.log(
    JSON.stringify({
      baseUrl,
      compareControlStyles,
      heroMetaFontSize,
      storyMicrocopyFontSize,
    }),
  );
} finally {
  await browser.close();
}
