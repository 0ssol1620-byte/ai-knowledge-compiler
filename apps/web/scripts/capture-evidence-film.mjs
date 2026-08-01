import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const root = resolve(import.meta.dirname, "../../..");
const output = resolve(root, "apps/web/public/film");
const scratch = resolve(output, ".capture");
const baseUrl = process.env.STRUCTARA_CAPTURE_URL ?? "http://127.0.0.1:3001";
const ffmpeg = process.env.STRUCTARA_FFMPEG;
if (!ffmpeg) throw new Error("STRUCTARA_FFMPEG must point to a validated ffmpeg binary");
const benchmarkSnapshot = JSON.parse(
  await readFile(resolve(root, "apps/web/src/data/benchmark-public-snapshot.json"), "utf8"),
);
const measuredCandidates = benchmarkSnapshot.datasets.filter(
  (candidate) => candidate.status === "available",
);
const formalCaseCount = measuredCandidates.reduce(
  (total, candidate) => total + (candidate.evidence?.case_count ?? 0),
  0,
);

const loops = [
  ["intake-dedupe", 0],
  ["adaptive-estimate", 1],
  ["page-block-detection", 2],
  ["cross-page-table", 3],
  ["numeric-proof", 3],
  ["auto-repair", 3],
  ["knowledge-relations", 5],
  ["export-ready", 7],
];

await rm(scratch, { recursive: true, force: true });
await mkdir(scratch, { recursive: true });
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });

const filmContext = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",
  recordVideo: { dir: scratch, size: { width: 1440, height: 900 } },
});
const filmPage = await filmContext.newPage();
const filmVideo = filmPage.video();
await filmPage.goto(`${baseUrl}/film?hold=1`, { waitUntil: "domcontentloaded", timeout: 30_000 });
await filmPage.waitForTimeout(60_500);
await filmContext.close();
const rawFilm = await filmVideo.path();
const webm = resolve(output, "structara-evidence-in-motion-60s.webm");
const mp4 = resolve(output, "structara-evidence-in-motion-60s.mp4");
const poster = resolve(output, "structara-evidence-in-motion-poster.webp");
const rawWebm = resolve(scratch, "film-raw.webm");
await rename(rawFilm, rawWebm);
await execFileAsync(ffmpeg, ["-y", "-i", rawWebm, "-t", "60", "-an", "-c:v", "copy", webm]);
await execFileAsync(ffmpeg, ["-y", "-i", rawWebm, "-t", "60", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4]);
await rm(rawWebm, { force: true });
await execFileAsync(ffmpeg, ["-y", "-ss", "27", "-i", mp4, "-frames:v", "1", "-vf", "scale=1440:-2", "-c:v", "libwebp", "-quality", "86", poster]);

const loopRecords = [];
for (let index = 0; index < loops.length; index += 1) {
  const [id, scene] = loops[index];
  const context = await browser.newContext({
    viewport: { width: 960, height: 600 },
    colorScheme: "light",
    recordVideo: { dir: scratch, size: { width: 960, height: 600 } },
  });
  const page = await context.newPage();
  const video = page.video();
  const route = `/film?scene=${scene}&static=1`;
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.waitForTimeout(3_200);
  await context.close();
  const source = await video.path();
  const target = resolve(output, `loop-${String(index + 1).padStart(2, "0")}-${id}.webm`);
  await rename(source, target);
  loopRecords.push({ id, route, file: target.split(/[\\/]/).at(-1), disclosure: "Sequence condensed for demonstration" });
}
await browser.close();

const captions = `WEBVTT\n\n00:00.000 --> 00:06.000\nRaw files become verified knowledge.\n\n00:06.000 --> 00:12.000\nCollect: hash, deduplicate, classify, and estimate.\n\n00:12.000 --> 00:18.000\nStructure: adaptive routes preserve page and block identity.\n\n00:18.000 --> 00:24.000\nVerify: numeric, table, continuity, and source hard gates.\n\n00:24.000 --> 00:30.000\nMeasured portfolio: ${formalCaseCount} formal inference cases.\n\n00:30.000 --> 00:36.000\nKnowledge: notes, entities, and evidence-backed relations.\n\n00:36.000 --> 00:42.000\nConnect: every relation can return to its source.\n\n00:42.000 --> 00:48.000\nPackage: Markdown, Obsidian, RAG JSONL, and JSON-LD.\n\n00:48.000 --> 00:60.000\nStructara. Compile the knowledge.\n`;
await writeFile(resolve(output, "structara-evidence-in-motion.en.vtt"), captions);

const files = ["structara-evidence-in-motion-60s.webm", "structara-evidence-in-motion-60s.mp4", "structara-evidence-in-motion-poster.webp", "structara-evidence-in-motion.en.vtt", ...loopRecords.map((item) => item.file)].sort();
const hashes = {};
for (const file of files) {
  hashes[file] = createHash("sha256").update(await readFile(resolve(output, file))).digest("hex");
}
await writeFile(resolve(output, "manifest.json"), `${JSON.stringify({
  schema_version: "1.0.0",
  title: "Evidence in Motion",
  truth_class: "measured-product-composite",
  measurement_scope: `OmniDocBench official demo 18 pages × 3 repeats × ${measuredCandidates.length} candidates`,
  formal_inference_case_count: formalCaseCount,
  evidence_bundle_sha256: benchmarkSnapshot.evidence_bundle_sha256,
  disclosure: "Product sequences are condensed; benchmark values are measured and independently hashed.",
  ending_hold_seconds: 12,
  film: { webm: files[files.indexOf("structara-evidence-in-motion-60s.webm")], mp4: "structara-evidence-in-motion-60s.mp4", poster: "structara-evidence-in-motion-poster.webp", captions: "structara-evidence-in-motion.en.vtt" },
  loops: loopRecords,
  sha256: hashes,
}, null, 2)}\n`);
console.log(`Captured one evidence film and ${loopRecords.length} micro loops.`);
