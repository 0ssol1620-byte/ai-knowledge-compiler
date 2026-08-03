import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const baseUrl = process.env.FOLYNTA_CAPTURE_URL ?? "http://127.0.0.1:3000";
const outputRoot = resolve(
  import.meta.dirname,
  "../../../artifacts/folynta-v1-visual-qa",
);
const viewports = [
  [1920, 1080],
  [1440, 900],
  [1024, 768],
  [390, 844],
];
const expectedScenes = [
  "01-product-film",
  "02-intake",
  "03-recovery",
  "04-actual-source",
  "05-knowledge",
  "06-trust",
  "07-final",
];

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const records = [];

for (const locale of ["ko", "en"]) {
  for (const reducedMotion of ["no-preference", "reduce"]) {
    for (const [width, height] of viewports) {
      console.log(`capturing ${locale}/${reducedMotion}/${width}x${height}`);
      const context = await browser.newContext({
        viewport: { width, height },
        reducedMotion,
        locale: locale === "ko" ? "ko-KR" : "en-US",
        colorScheme: "light",
      });
      await context.addCookies([
        { name: "akc_locale", value: locale, url: baseUrl, sameSite: "Lax" },
      ]);
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("pageerror", (error) => pageErrors.push(error.message));
      const response = await page.goto(baseUrl, {
        waitUntil: "networkidle",
        timeout: 60_000,
      });
      await page.locator("main").waitFor({ state: "visible" });
      const defaultMarket = await page
        .locator('[data-scene="04-actual-source"] [data-market]')
        .getAttribute("data-market");
      if (defaultMarket !== (locale === "ko" ? "dart" : "sec")) {
        throw new Error(`locale market mismatch: ${locale}/${defaultMarket}`);
      }
      await page
        .locator('[data-scene="04-actual-source"]')
        .scrollIntoViewIfNeeded();
      if (locale === "en") {
        await page.getByRole("button", { name: "DART · KR" }).click();
      }
      const pdfBoundary = page.locator('[class*="pdfBoundary"]');
      await pdfBoundary.waitFor({ state: "attached", timeout: 30_000 });
      await pdfBoundary.scrollIntoViewIfNeeded();
      const pdfRenderer = page.locator("[data-render-state]");
      await pdfRenderer.waitFor({
        state: "attached",
        timeout: 30_000,
      });
      await page.waitForFunction(
        () =>
          document
            .querySelector("[data-render-state]")
            ?.getAttribute("data-render-state") !== "loading",
        undefined,
        { timeout: 30_000 },
      );
      const pdfRenderState = await page
        .locator("[data-render-state]")
        .getAttribute("data-render-state");
      if (pdfRenderState !== "ready") {
        throw new Error(`PDF render state: ${pdfRenderState}`);
      }
      const sceneIds = await page
        .locator("main > section")
        .evaluateAll((nodes) =>
          nodes.map((node) => node.getAttribute("data-scene")),
        );
      if (JSON.stringify(sceneIds) !== JSON.stringify(expectedScenes)) {
        throw new Error(`scene mismatch: ${JSON.stringify(sceneIds)}`);
      }
      await page
        .getByRole("button", {
          name: locale === "ko" ? "누락 행 복구" : "Recover missing row",
        })
        .click();
      await page
        .getByRole("button", {
          name: locale === "ko" ? "원문으로 검증" : "Verify against source",
        })
        .click();
      const inspection = await page.evaluate(() => ({
        bodyTextLength: document.body.innerText.trim().length,
        h1Count: document.querySelectorAll("h1").length,
        overflowX:
          Math.max(
            document.documentElement.scrollWidth,
            document.body.scrollWidth,
          ) - window.innerWidth,
        errorOverlay: Boolean(
          document.querySelector(
            "[data-nextjs-dialog],.vite-error-overlay,#webpack-dev-server-client-overlay",
          ),
        ),
        pdfCanvas: {
          width: document.querySelector("canvas")?.width ?? 0,
          height: document.querySelector("canvas")?.height ?? 0,
        },
        recoveryState:
          document
            .querySelector('[data-scene="03-recovery"] [data-state]')
            ?.getAttribute("data-state") ??
          document
            .querySelector('[data-scene="03-recovery"]')
            ?.querySelector('[class*="recoveryFrame"]')
            ?.getAttribute("data-state"),
      }));
      if (
        response === null ||
        response.status() >= 400 ||
        inspection.bodyTextLength < 500 ||
        inspection.h1Count !== 1 ||
        inspection.overflowX > 1 ||
        inspection.errorOverlay ||
        inspection.pdfCanvas.width < 100 ||
        inspection.pdfCanvas.height < 100 ||
        consoleErrors.length ||
        pageErrors.length
      ) {
        throw new Error(
          JSON.stringify({
            status: response?.status(),
            inspection,
            consoleErrors,
            pageErrors,
          }),
        );
      }
      await page.addStyleTag({
        content:
          "*{caret-color:transparent!important}.folynta-v4-home>section{content-visibility:visible!important}",
      });
      const directory = resolve(
        outputRoot,
        locale,
        reducedMotion === "reduce" ? "reduced" : "default",
        `${width}x${height}`,
      );
      await mkdir(directory, { recursive: true });
      const screenshot = await page.screenshot({
        path: resolve(directory, "home.webp"),
        fullPage: true,
        type: "webp",
        quality: 82,
        animations: "disabled",
      });
      records.push({
        locale,
        reduced_motion: reducedMotion === "reduce",
        viewport: { width, height },
        status: response.status(),
        scene_ids: sceneIds,
        inspection,
        console_errors: consoleErrors,
        page_errors: pageErrors,
        screenshot_sha256: createHash("sha256")
          .update(screenshot)
          .digest("hex"),
      });
      await context.close();
    }
  }
}

await browser.close();
await writeFile(
  resolve(outputRoot, "report.json"),
  `${JSON.stringify({ schema_version: "1.0", base_url: baseUrl, records }, null, 2)}\n`,
  "utf8",
);
console.log(`FOLYNTA v1 visual QA passed: ${records.length} captures`);
