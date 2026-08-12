import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const repositoryRoot = resolve(import.meta.dirname, "../../..");
const outputRoot = resolve(repositoryRoot, "artifacts/v4-brand-captures");
const baseUrl = new URL(
  process.env.STRUCTARA_CAPTURE_URL ?? "http://127.0.0.1:3100",
);

const routes = [
  ["home", "/", "marketing"],
  ["product", "/product", "marketing"],
  ["benchmarks", "/benchmarks", "marketing"],
  ["security", "/security", "marketing"],
  ["pricing", "/pricing", "marketing"],
  ["intake", "/intake", "product"],
  ["workspace", "/workspace", "product"],
  ["integrity", "/integrity", "product"],
  ["knowledge-bases", "/knowledge-bases", "product"],
  [
    "evidence-graph",
    "/app/projects/project_research/graph",
    "signature_support",
  ],
  [
    "package-export",
    "/app/projects/project_research/exports",
    "signature_support",
  ],
  ["demo-dart", "/demo/dart", "public_proof"],
  ["demo-sec", "/demo/sec", "public_proof"],
];
const narrativeScenes = [
  ["01-hero", '[data-scene="01-hero"]'],
  ["02-processing", '[data-scene="02-processing"]'],
  ["03-proof", '[data-scene="03-proof"]'],
  ["04-transformation", '[data-scene="04-transformation"]'],
  ["05-knowledge", '[data-scene="05-knowledge"]'],
  ["06-trust-security", '[data-scene="06-trust-security"]'],
  ["07-final", '[data-scene="07-final"]'],
];
const viewports = [
  [1920, 1080],
  [1440, 900],
  [1280, 800],
  [1024, 768],
  [768, 1024],
  [390, 844],
  [360, 800],
];
const locales = ["en", "ko"];
const motionModes = [
  ["default", "no-preference"],
  ["reduced-motion", "reduce"],
];

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function webpDimensions(bytes) {
  if (
    bytes.length < 30 ||
    bytes.toString("ascii", 0, 4) !== "RIFF" ||
    bytes.toString("ascii", 8, 12) !== "WEBP"
  ) {
    throw new Error("capture is not a RIFF WebP image");
  }
  let offset = 12;
  while (offset + 8 <= bytes.length) {
    const chunk = bytes.toString("ascii", offset, offset + 4);
    const size = bytes.readUInt32LE(offset + 4);
    const data = offset + 8;
    if (data + size > bytes.length) {
      throw new Error(`truncated WebP ${chunk} chunk`);
    }
    if (chunk === "VP8X" && size >= 10) {
      return {
        width: bytes.readUIntLE(data + 4, 3) + 1,
        height: bytes.readUIntLE(data + 7, 3) + 1,
      };
    }
    if (chunk === "VP8L" && size >= 5 && bytes[data] === 0x2f) {
      const packed = bytes.readUInt32LE(data + 1);
      return {
        width: (packed & 0x3fff) + 1,
        height: ((packed >>> 14) & 0x3fff) + 1,
      };
    }
    if (
      chunk === "VP8 " &&
      size >= 10 &&
      bytes[data + 3] === 0x9d &&
      bytes[data + 4] === 0x01 &&
      bytes[data + 5] === 0x2a
    ) {
      return {
        width: bytes.readUInt16LE(data + 6) & 0x3fff,
        height: bytes.readUInt16LE(data + 8) & 0x3fff,
      };
    }
    offset = data + size + (size % 2);
  }
  throw new Error("WebP dimensions are unavailable");
}

async function gitEvidence() {
  const options = {
    cwd: repositoryRoot,
    windowsHide: true,
    maxBuffer: 64 << 20,
  };
  const [
    { stdout: revision },
    { stdout: status },
    { stdout: diff },
    { stdout: untracked },
  ] = await Promise.all([
    execFileAsync("git", ["rev-parse", "HEAD"], options),
    execFileAsync("git", ["status", "--short"], options),
    execFileAsync(
      "git",
      [
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
        ".",
        ":(exclude)artifacts",
      ],
      options,
    ),
    execFileAsync(
      "git",
      ["ls-files", "--others", "--exclude-standard", "-z"],
      options,
    ),
  ]);
  const untrackedDigest = createHash("sha256");
  const untrackedPaths = untracked.split("\0").filter(Boolean).sort();
  for (const relativePath of untrackedPaths) {
    untrackedDigest.update(relativePath);
    untrackedDigest.update("\0");
    untrackedDigest.update(
      await readFile(resolve(repositoryRoot, relativePath)),
    );
    untrackedDigest.update("\0");
  }
  return {
    revision: revision.trim(),
    worktree_status_sha256: sha256(status.replaceAll("\r\n", "\n")),
    worktree_diff_sha256: sha256(diff.replaceAll("\r\n", "\n")),
    worktree_untracked_sha256: untrackedDigest.digest("hex"),
    untracked_path_count: untrackedPaths.length,
    dirty_path_count: status.split(/\r?\n/u).filter(Boolean).length,
  };
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const records = [];

for (const locale of locales) {
  for (const [motion, reducedMotion] of motionModes) {
    for (const [width, height] of viewports) {
      const context = await browser.newContext({
        viewport: { width, height },
        colorScheme: "light",
        reducedMotion,
        locale: locale === "ko" ? "ko-KR" : "en-US",
        deviceScaleFactor: 1,
      });
      await context.addCookies([
        {
          name: "structara_locale",
          value: locale,
          url: baseUrl.origin,
          sameSite: "Lax",
        },
      ]);
      await context.addInitScript(() => {
        window.__STRUCTARA_CAPTURE_CLS__ = {
          value: 0,
          sessionValue: 0,
          sessionStart: 0,
          lastEntry: 0,
        };
        new PerformanceObserver((entries) => {
          for (const entry of entries.getEntries()) {
            if (!entry.hadRecentInput) {
              const cls = window.__STRUCTARA_CAPTURE_CLS__;
              const startsNewSession =
                cls.sessionStart === 0 ||
                entry.startTime - cls.lastEntry > 1_000 ||
                entry.startTime - cls.sessionStart > 5_000;
              if (startsNewSession) {
                cls.sessionStart = entry.startTime;
                cls.sessionValue = entry.value;
              } else {
                cls.sessionValue += entry.value;
              }
              cls.lastEntry = entry.startTime;
              cls.value = Math.max(cls.value, cls.sessionValue);
            }
          }
        }).observe({ type: "layout-shift", buffered: true });
      });

      for (const [name, route, routeSet] of routes) {
        const page = await context.newPage();
        const consoleErrors = [];
        page.on("console", (message) => {
          if (message.type() === "error") consoleErrors.push(message.text());
        });
        const response = await page.goto(new URL(route, baseUrl).href, {
          waitUntil: "domcontentloaded",
          timeout: 45_000,
        });
        await page
          .locator("main")
          .first()
          .waitFor({ state: "visible", timeout: 20_000 });
        await page.waitForTimeout(700);
        await page.addStyleTag({
          content:
            "html{scroll-behavior:auto!important}*{caret-color:transparent!important}.nextjs-toast{display:none!important}",
        });

        const inspection = await page.evaluate(
          ({ expectedLocale }) => {
            const root = document.documentElement;
            const isVisible = (element) => {
              const box = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              if (
                element.closest(
                  ".sr-only,.visually-hidden,[hidden],[aria-hidden='true']",
                ) ||
                (box.width <= 1 &&
                  box.height <= 1 &&
                  (style.position === "absolute" ||
                    style.clipPath !== "none" ||
                    style.overflow === "hidden"))
              ) {
                return false;
              }
              return (
                box.width > 0 &&
                box.height > 0 &&
                box.right > 0 &&
                box.bottom > 0 &&
                box.left < window.innerWidth &&
                box.top < window.innerHeight &&
                style.display !== "none" &&
                style.visibility !== "hidden" &&
                Number.parseFloat(style.opacity || "1") > 0.01
              );
            };
            const describe = (element, size) => ({
              tag: element.tagName.toLowerCase(),
              class_name: String(element.className || "").slice(0, 160),
              text: (
                element.textContent ||
                element.getAttribute("aria-label") ||
                ""
              )
                .replace(/\s+/gu, " ")
                .trim()
                .slice(0, 160),
              font_size_px: Number(size.toFixed(3)),
            });
            const visibleTextBelow12 = [...document.querySelectorAll("body *")]
              .filter((element) => {
                const hasOwnText = [...element.childNodes].some(
                  (node) =>
                    node.nodeType === Node.TEXT_NODE &&
                    Boolean(node.textContent?.trim()),
                );
                if (!hasOwnText || !isVisible(element)) return false;
                return (
                  Number.parseFloat(getComputedStyle(element).fontSize) < 11.99
                );
              })
              .slice(0, 20)
              .map((element) =>
                describe(
                  element,
                  Number.parseFloat(getComputedStyle(element).fontSize),
                ),
              );
            const coreTextBelow14 = [
              ...document.querySelectorAll(
                "button,input,select,textarea,label,[role='button'],[role='tab'],[role='option']",
              ),
            ]
              .filter((element) => {
                if (!isVisible(element)) return false;
                const text =
                  element.textContent ||
                  element.value ||
                  element.getAttribute("placeholder") ||
                  "";
                return (
                  Boolean(text.trim()) &&
                  Number.parseFloat(getComputedStyle(element).fontSize) < 13.99
                );
              })
              .slice(0, 20)
              .map((element) =>
                describe(
                  element,
                  Number.parseFloat(getComputedStyle(element).fontSize),
                ),
              );
            const minimumTarget = window.innerWidth <= 768 ? 43.99 : 23.99;
            const undersizedCoreTargets = [
              ...document.querySelectorAll(
                "button,input,select,textarea,[role='button'],[role='tab']",
              ),
            ]
              .filter((element) => {
                if (!isVisible(element) || element.disabled) return false;
                const box = element.getBoundingClientRect();
                return box.width < minimumTarget || box.height < minimumTarget;
              })
              .slice(0, 20)
              .map((element) => {
                const box = element.getBoundingClientRect();
                return {
                  tag: element.tagName.toLowerCase(),
                  text: (
                    element.textContent ||
                    element.getAttribute("aria-label") ||
                    ""
                  )
                    .replace(/\s+/gu, " ")
                    .trim()
                    .slice(0, 160),
                  width_px: Number(box.width.toFixed(3)),
                  height_px: Number(box.height.toFixed(3)),
                  required_px: minimumTarget,
                };
              });
            const clippedCoreText = [
              ...document.querySelectorAll(
                "h1,h2,h3,h4,button,label,[role='heading'],[role='button'],[role='tab']",
              ),
            ]
              .filter((element) => {
                if (!isVisible(element) || !(element.textContent || "").trim())
                  return false;
                const style = getComputedStyle(element);
                const clipsX = ["hidden", "clip"].includes(style.overflowX);
                const clipsY = ["hidden", "clip"].includes(style.overflowY);
                return (
                  (clipsX && element.scrollWidth > element.clientWidth + 1) ||
                  (clipsY && element.scrollHeight > element.clientHeight + 1)
                );
              })
              .slice(0, 20)
              .map((element) => ({
                tag: element.tagName.toLowerCase(),
                text: (element.textContent || "")
                  .replace(/\s+/gu, " ")
                  .trim()
                  .slice(0, 160),
                client_width_px: element.clientWidth,
                scroll_width_px: element.scrollWidth,
                client_height_px: element.clientHeight,
                scroll_height_px: element.scrollHeight,
              }));
            const visibleBrokenImages = [...document.images].filter(
              (element) => {
                return (
                  isVisible(element) &&
                  element.complete &&
                  element.naturalWidth === 0
                );
              },
            );
            const bodyText = document.body.innerText
              .replace(/\s+/gu, " ")
              .trim();
            const mainText = (document.querySelector("main")?.innerText || "")
              .replace(/\s+/gu, " ")
              .trim();
            const truthMarkerPresent = Boolean(
              document.querySelector(
                "[data-truth-class],[data-reference-snapshot],[data-signature-asset],[data-signature-assets],[data-evidence]",
              ),
            );
            return {
              title: document.title,
              html_lang: root.lang,
              expected_locale: expectedLocale,
              main_present: Boolean(document.querySelector("main")),
              horizontal_overflow_px: Math.max(
                0,
                root.scrollWidth - root.clientWidth,
              ),
              visible_broken_images: visibleBrokenImages.map(
                (element) => element.currentSrc || element.src,
              ),
              cumulative_layout_shift: Number(
                (window.__STRUCTARA_CAPTURE_CLS__?.value ?? 0).toFixed(5),
              ),
              visible_text_below_12px: visibleTextBelow12,
              core_text_below_14px: coreTextBelow14,
              undersized_core_targets: undersizedCoreTargets,
              clipped_core_text: clippedCoreText,
              body_text_length: bodyText.length,
              main_text_length: mainText.length,
              truth_label_present:
                truthMarkerPresent ||
                /actual product|deterministic|illustrative|not measured|production evidence required|demo workspace|reference|public filing|public fixture|sample|실제 제품|결정론|예시|측정되지|프로덕션 근거|데모|참조|공시/iu.test(
                  bodyText,
                ),
            };
          },
          { expectedLocale: locale },
        );

        const file = `${name}__${locale}__${width}x${height}__${motion}.webp`;
        const filePath = resolve(outputRoot, file);
        await page.screenshot({
          path: filePath,
          type: "webp",
          quality: 86,
          animations: "disabled",
          fullPage: false,
        });
        const bytes = await readFile(filePath);
        records.push({
          route,
          route_set: routeSet,
          scene: "above_fold",
          locale,
          motion,
          viewport: { width, height },
          response_status: response?.status() ?? null,
          file,
          sha256: sha256(bytes),
          console_errors: consoleErrors,
          inspection,
        });
        await page.close();
      }

      const signaturePage = await context.newPage();
      const signatureConsoleErrors = [];
      signaturePage.on("console", (message) => {
        if (message.type() === "error")
          signatureConsoleErrors.push(message.text());
      });
      const signatureResponse = await signaturePage.goto(baseUrl.href, {
        waitUntil: "domcontentloaded",
        timeout: 45_000,
      });
      await signaturePage.locator("main").first().waitFor({
        state: "visible",
        timeout: 20_000,
      });
      await signaturePage.waitForTimeout(700);
      await signaturePage.addStyleTag({
        content:
          "html{scroll-behavior:auto!important}*{caret-color:transparent!important}.nextjs-toast{display:none!important}",
      });
      const signatureInspection = await signaturePage.evaluate(
        ({ expectedLocale }) => {
          const root = document.documentElement;
          const isVisible = (element) => {
            const box = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            if (
              element.closest(
                ".sr-only,.visually-hidden,[hidden],[aria-hidden='true']",
              ) ||
              (box.width <= 1 &&
                box.height <= 1 &&
                (style.position === "absolute" ||
                  style.clipPath !== "none" ||
                  style.overflow === "hidden"))
            ) {
              return false;
            }
            return (
              box.width > 0 &&
              box.height > 0 &&
              box.right > 0 &&
              box.bottom > 0 &&
              box.left < window.innerWidth &&
              box.top < window.innerHeight &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              Number.parseFloat(style.opacity || "1") > 0.01
            );
          };
          const describe = (element, size) => ({
            tag: element.tagName.toLowerCase(),
            class_name: String(element.className || "").slice(0, 160),
            text: (
              element.textContent ||
              element.getAttribute("aria-label") ||
              ""
            )
              .replace(/\s+/gu, " ")
              .trim()
              .slice(0, 160),
            font_size_px: Number(size.toFixed(3)),
          });
          const visibleTextBelow12 = [...document.querySelectorAll("body *")]
            .filter((element) => {
              const hasOwnText = [...element.childNodes].some(
                (node) =>
                  node.nodeType === Node.TEXT_NODE &&
                  Boolean(node.textContent?.trim()),
              );
              if (!hasOwnText || !isVisible(element)) return false;
              return (
                Number.parseFloat(getComputedStyle(element).fontSize) < 11.99
              );
            })
            .slice(0, 20)
            .map((element) =>
              describe(
                element,
                Number.parseFloat(getComputedStyle(element).fontSize),
              ),
            );
          const coreTextBelow14 = [
            ...document.querySelectorAll(
              "button,input,select,textarea,label,[role='button'],[role='tab'],[role='option']",
            ),
          ]
            .filter((element) => {
              if (!isVisible(element)) return false;
              const text =
                element.textContent ||
                element.value ||
                element.getAttribute("placeholder") ||
                "";
              return (
                Boolean(text.trim()) &&
                Number.parseFloat(getComputedStyle(element).fontSize) < 13.99
              );
            })
            .slice(0, 20)
            .map((element) =>
              describe(
                element,
                Number.parseFloat(getComputedStyle(element).fontSize),
              ),
            );
          const minimumTarget = window.innerWidth <= 768 ? 43.99 : 23.99;
          const undersizedCoreTargets = [
            ...document.querySelectorAll(
              "button,input,select,textarea,[role='button'],[role='tab']",
            ),
          ]
            .filter((element) => {
              if (!isVisible(element) || element.disabled) return false;
              const box = element.getBoundingClientRect();
              return box.width < minimumTarget || box.height < minimumTarget;
            })
            .slice(0, 20)
            .map((element) => {
              const box = element.getBoundingClientRect();
              return {
                tag: element.tagName.toLowerCase(),
                text: (
                  element.textContent ||
                  element.getAttribute("aria-label") ||
                  ""
                )
                  .replace(/\s+/gu, " ")
                  .trim()
                  .slice(0, 160),
                width_px: Number(box.width.toFixed(3)),
                height_px: Number(box.height.toFixed(3)),
                required_px: minimumTarget,
              };
            });
          const clippedCoreText = [
            ...document.querySelectorAll(
              "h1,h2,h3,h4,button,label,[role='heading'],[role='button'],[role='tab']",
            ),
          ]
            .filter((element) => {
              if (!isVisible(element) || !(element.textContent || "").trim())
                return false;
              const style = getComputedStyle(element);
              const clipsX = ["hidden", "clip"].includes(style.overflowX);
              const clipsY = ["hidden", "clip"].includes(style.overflowY);
              return (
                (clipsX && element.scrollWidth > element.clientWidth + 1) ||
                (clipsY && element.scrollHeight > element.clientHeight + 1)
              );
            })
            .slice(0, 20)
            .map((element) => ({
              tag: element.tagName.toLowerCase(),
              text: (element.textContent || "")
                .replace(/\s+/gu, " ")
                .trim()
                .slice(0, 160),
              client_width_px: element.clientWidth,
              scroll_width_px: element.scrollWidth,
              client_height_px: element.clientHeight,
              scroll_height_px: element.scrollHeight,
            }));
          const visibleBrokenImages = [...document.images].filter((element) => {
            return (
              isVisible(element) &&
              element.complete &&
              element.naturalWidth === 0
            );
          });
          return {
            title: document.title,
            html_lang: root.lang,
            expected_locale: expectedLocale,
            main_present: Boolean(document.querySelector("main")),
            horizontal_overflow_px: Math.max(
              0,
              root.scrollWidth - root.clientWidth,
            ),
            visible_broken_images: visibleBrokenImages.map(
              (element) => element.currentSrc || element.src,
            ),
            cumulative_layout_shift: Number(
              (window.__STRUCTARA_CAPTURE_CLS__?.value ?? 0).toFixed(5),
            ),
            visible_text_below_12px: visibleTextBelow12,
            core_text_below_14px: coreTextBelow14,
            undersized_core_targets: undersizedCoreTargets,
            clipped_core_text: clippedCoreText,
            body_text_length: document.body.innerText.trim().length,
            main_text_length: (
              document.querySelector("main")?.innerText || ""
            ).trim().length,
            truth_label_present: Boolean(
              document.querySelector(
                "[data-truth-class],[data-reference-snapshot]",
              ),
            ),
          };
        },
        { expectedLocale: locale },
      );
      for (const [sceneId, selector] of narrativeScenes) {
        const scene = `narrative_${sceneId}`;
        const locator = signaturePage.locator(selector).first();
        await locator.waitFor({ state: "visible", timeout: 20_000 });
        await locator.scrollIntoViewIfNeeded();
        const assetInspection = await locator.evaluate((element) => {
          const box = element.getBoundingClientRect();
          const isRendered = (child) => {
            const childBox = child.getBoundingClientRect();
            const style = getComputedStyle(child);
            if (
              child.closest(
                ".sr-only,.visually-hidden,[hidden],[aria-hidden='true']",
              ) ||
              (childBox.width <= 1 &&
                childBox.height <= 1 &&
                (style.position === "absolute" ||
                  style.clipPath !== "none" ||
                  style.overflow === "hidden"))
            ) {
              return false;
            }
            return (
              childBox.width > 0 &&
              childBox.height > 0 &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              Number.parseFloat(style.opacity || "1") > 0.01
            );
          };
          const describe = (child, size) => ({
            tag: child.tagName.toLowerCase(),
            class_name: String(child.className || "").slice(0, 160),
            text: (child.textContent || child.getAttribute("aria-label") || "")
              .replace(/\s+/gu, " ")
              .trim()
              .slice(0, 160),
            font_size_px: Number(size.toFixed(3)),
          });
          const visibleTextBelow12 = [...element.querySelectorAll("*")]
            .filter((child) => {
              const hasOwnText = [...child.childNodes].some(
                (node) =>
                  node.nodeType === Node.TEXT_NODE &&
                  Boolean(node.textContent?.trim()),
              );
              return (
                hasOwnText &&
                isRendered(child) &&
                Number.parseFloat(getComputedStyle(child).fontSize) < 11.99
              );
            })
            .slice(0, 20)
            .map((child) =>
              describe(
                child,
                Number.parseFloat(getComputedStyle(child).fontSize),
              ),
            );
          const coreTextBelow14 = [
            ...element.querySelectorAll(
              "button,input,select,textarea,label,[role='button'],[role='tab'],[role='option']",
            ),
          ]
            .filter((child) => {
              if (!isRendered(child)) return false;
              const text =
                child.textContent ||
                child.value ||
                child.getAttribute("placeholder") ||
                "";
              return (
                Boolean(text.trim()) &&
                Number.parseFloat(getComputedStyle(child).fontSize) < 13.99
              );
            })
            .slice(0, 20)
            .map((child) =>
              describe(
                child,
                Number.parseFloat(getComputedStyle(child).fontSize),
              ),
            );
          const minimumTarget = window.innerWidth <= 768 ? 43.99 : 23.99;
          const undersizedCoreTargets = [
            ...element.querySelectorAll(
              "button,input,select,textarea,[role='button'],[role='tab']",
            ),
          ]
            .filter((child) => {
              if (!isRendered(child) || child.disabled) return false;
              const childBox = child.getBoundingClientRect();
              return (
                childBox.width < minimumTarget ||
                childBox.height < minimumTarget
              );
            })
            .slice(0, 20)
            .map((child) => {
              const childBox = child.getBoundingClientRect();
              return {
                tag: child.tagName.toLowerCase(),
                text: (
                  child.textContent ||
                  child.getAttribute("aria-label") ||
                  ""
                )
                  .replace(/\s+/gu, " ")
                  .trim()
                  .slice(0, 160),
                width_px: Number(childBox.width.toFixed(3)),
                height_px: Number(childBox.height.toFixed(3)),
                required_px: minimumTarget,
              };
            });
          const clippedCoreText = [
            ...element.querySelectorAll(
              "h1,h2,h3,h4,button,label,[role='heading'],[role='button'],[role='tab']",
            ),
          ]
            .filter((child) => {
              if (!isRendered(child) || !(child.textContent || "").trim())
                return false;
              const style = getComputedStyle(child);
              const clipsX = ["hidden", "clip"].includes(style.overflowX);
              const clipsY = ["hidden", "clip"].includes(style.overflowY);
              return (
                (clipsX && child.scrollWidth > child.clientWidth + 1) ||
                (clipsY && child.scrollHeight > child.clientHeight + 1)
              );
            })
            .slice(0, 20)
            .map((child) => ({
              tag: child.tagName.toLowerCase(),
              text: (child.textContent || "")
                .replace(/\s+/gu, " ")
                .trim()
                .slice(0, 160),
              client_width_px: child.clientWidth,
              scroll_width_px: child.scrollWidth,
              client_height_px: child.clientHeight,
              scroll_height_px: child.scrollHeight,
            }));
          const truthBoundary =
            element.closest("[data-truth-class],[data-reference-snapshot]") ||
            element.querySelector(
              "[data-truth-class],[data-reference-snapshot]",
            );
          return {
            asset_width_px: Math.round(box.width),
            asset_height_px: Math.round(box.height),
            asset_text_length: (element.textContent ?? "").trim().length,
            asset_visible_text_below_12px: visibleTextBelow12,
            asset_core_text_below_14px: coreTextBelow14,
            asset_undersized_core_targets: undersizedCoreTargets,
            asset_clipped_core_text: clippedCoreText,
            asset_truth_label_present: Boolean(truthBoundary),
            asset_broken_images: [...element.querySelectorAll("img")]
              .filter((image) => image.complete && image.naturalWidth === 0)
              .map((image) => image.currentSrc || image.src),
          };
        });
        const file = `narrative-${sceneId.toLowerCase()}__${locale}__${width}x${height}__${motion}.webp`;
        const filePath = resolve(outputRoot, file);
        await locator.screenshot({
          path: filePath,
          type: "webp",
          quality: 86,
          animations: "disabled",
        });
        const bytes = await readFile(filePath);
        const dimensions = webpDimensions(bytes);
        records.push({
          route: "/",
          route_set: "homepage_narrative_scene",
          scene,
          locale,
          motion,
          viewport: { width, height },
          response_status: signatureResponse?.status() ?? null,
          file,
          sha256: sha256(bytes),
          console_errors: signatureConsoleErrors,
          inspection: {
            ...signatureInspection,
            ...assetInspection,
            asset_width_px: dimensions.width,
            asset_height_px: dimensions.height,
            visible_broken_images: [
              ...signatureInspection.visible_broken_images,
              ...assetInspection.asset_broken_images,
            ],
            visible_text_below_12px: [
              ...signatureInspection.visible_text_below_12px,
              ...assetInspection.asset_visible_text_below_12px,
            ],
            core_text_below_14px: [
              ...signatureInspection.core_text_below_14px,
              ...assetInspection.asset_core_text_below_14px,
            ],
            undersized_core_targets: [
              ...signatureInspection.undersized_core_targets,
              ...assetInspection.asset_undersized_core_targets,
            ],
            clipped_core_text: [
              ...signatureInspection.clipped_core_text,
              ...assetInspection.asset_clipped_core_text,
            ],
            truth_label_present: assetInspection.asset_truth_label_present,
          },
        });
      }
      await signaturePage.close();
      console.log(
        `Captured ${locale} / ${motion} / ${width}x${height} (${records.length}/${(routes.length + narrativeScenes.length) * viewports.length * locales.length * motionModes.length}).`,
      );
      await context.close();
    }
  }
}

await browser.close();
const buildId = (
  await readFile(resolve(repositoryRoot, "apps/web/.next/BUILD_ID"), "utf8")
).trim();
const blockers = records.flatMap((record) => {
  const findings = [];
  if (record.response_status === null || record.response_status >= 400) {
    findings.push("navigation_failed");
  }
  if (
    !record.inspection.main_present ||
    record.inspection.main_text_length === 0
  ) {
    findings.push("empty_main");
  }
  if (
    record.scene.startsWith("narrative_") &&
    (record.inspection.asset_width_px <= 0 ||
      record.inspection.asset_height_px <= 0 ||
      record.inspection.asset_text_length <= 0)
  ) {
    findings.push("empty_narrative_scene");
  }
  if (record.inspection.horizontal_overflow_px > 0) {
    findings.push("horizontal_overflow");
  }
  if (record.inspection.visible_broken_images.length > 0) {
    findings.push("visible_broken_image");
  }
  if (record.inspection.visible_text_below_12px.length > 0) {
    findings.push("visible_text_below_12px");
  }
  if (record.inspection.core_text_below_14px.length > 0) {
    findings.push("core_text_below_14px");
  }
  if (record.inspection.undersized_core_targets.length > 0) {
    findings.push("undersized_core_target");
  }
  if (record.inspection.clipped_core_text.length > 0) {
    findings.push("clipped_core_text");
  }
  if (record.console_errors.length > 0) {
    findings.push("console_error");
  }
  if (!record.inspection.html_lang.startsWith(record.locale)) {
    findings.push("locale_mismatch");
  }
  if (record.inspection.cumulative_layout_shift > 0.1) {
    findings.push("layout_shift_above_lab_guardrail");
  }
  if (!record.inspection.truth_label_present) {
    findings.push("missing_product_or_proof_truth_label");
  }
  return findings.map((finding) => ({
    route: record.route,
    scene: record.scene,
    locale: record.locale,
    motion: record.motion,
    viewport: record.viewport,
    finding,
  }));
});
const manifest = {
  schema_version: "1.0",
  captured_at: new Date().toISOString(),
  capture_contract: {
    actual_routes_only: true,
    current_worktree_only: true,
    screenshot_kind: "named_scene_crop",
    scenes: [
      "above_fold",
      ...narrativeScenes.map(([sceneId]) => `narrative_${sceneId}`),
    ],
    exact_widths_px: viewports.map(([width]) => width),
    languages: locales,
    modes: motionModes.map(([name]) => name),
    computed_text_floor_px: 12,
    computed_core_text_floor_px: 14,
    core_target_floor_px: { desktop: 24, mobile: 44 },
    expected_capture_count:
      (routes.length + narrativeScenes.length) *
      viewports.length *
      locales.length *
      motionModes.length,
    homepage_narrative_scenes: narrativeScenes.map(([sceneId]) => sceneId),
  },
  application: {
    base_url: baseUrl.origin,
    next_build_id: buildId,
    demo_disclosure:
      "Demo mode is a deterministic reference workspace, not production or customer evidence.",
    ...(await gitEvidence()),
  },
  summary: {
    capture_count: records.length,
    blocking_finding_count: blockers.length,
    approval: blockers.length === 0,
  },
  blocking_findings: blockers,
  records,
};
await writeFile(
  resolve(outputRoot, "capture-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
await writeFile(
  resolve(outputRoot, "hashes.sha256"),
  `${records.map((record) => `${record.sha256}  ${record.file}`).join("\n")}\n`,
);

console.log(
  `Captured ${records.length} current-worktree scenes; ${blockers.length} blocking automated findings.`,
);
if (blockers.length > 0) process.exitCode = 1;
