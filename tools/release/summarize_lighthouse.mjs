import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");

for (const profile of ["desktop", "mobile"]) {
  const report = JSON.parse(
    await readFile(
      resolve(root, `artifacts/lighthouse/folynta-v3-${profile}.json`),
      "utf8",
    ),
  );
  const categories = report.categories;
  const audits = report.audits;
  console.log(
    JSON.stringify({
      profile,
      performance: Math.round(categories.performance.score * 100),
      accessibility: Math.round(categories.accessibility.score * 100),
      best_practices: Math.round(categories["best-practices"].score * 100),
      seo: Math.round(categories.seo.score * 100),
      lcp_ms: Math.round(audits["largest-contentful-paint"].numericValue),
      cls: audits["cumulative-layout-shift"].numericValue,
      tbt_ms: Math.round(audits["total-blocking-time"].numericValue),
      accessibility_failures: categories.accessibility.auditRefs
        .map(({ id }) => audits[id])
        .filter((audit) => audit?.score !== null && audit?.score < 1)
        .map((audit) => ({
          id: audit.id,
          title: audit.title,
          nodes: (audit.details?.items ?? []).slice(0, 10).map((item) => ({
            selector: item.node?.selector,
            snippet: item.node?.snippet,
            explanation: item.node?.explanation,
          })),
        })),
    }),
  );
}
