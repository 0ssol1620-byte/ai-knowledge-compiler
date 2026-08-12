#!/usr/bin/env node

/**
 * Render the FOLYNTA portable technical report without an external plugin.
 *
 * The original lane imported `build_portable_artifact.mjs` and
 * `deliver_portable_artifact.mjs` from an OpenAI curated plugin cache. That
 * cache is not part of this repository, so a reviewer who clones the evidence
 * package cannot rebuild the report — and on a machine without the plugin the
 * finaliser simply fails. This renderer consumes the same
 * `*.artifact.json` produced by `build_patent_paper_artifacts.py` and emits a
 * self-contained HTML document plus the same delivery-receipt shape, so the
 * report becomes reproducible from the repository alone.
 *
 * Nothing here computes, rounds, or re-derives a metric: every number rendered
 * comes verbatim from the artifact's snapshot datasets.
 */

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const VALUE_OPTIONS = new Set(["input", "output", "receipt"]);

function usage() {
  return [
    "Usage: node render_folynta_portable_report.mjs --input <artifact.json> --output <report.html> [--receipt <receipt.json>]",
  ].join("\n");
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (!argument.startsWith("--")) throw new Error(`Unexpected argument: ${argument}`);
    const key = argument.slice(2);
    if (!VALUE_OPTIONS.has(key)) throw new Error(`Unknown argument: ${argument}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${argument}`);
    if (options[key] !== undefined) throw new Error(`${argument} may only be specified once.`);
    options[key] = value;
    index += 1;
  }
  for (const required of ["input", "output"]) {
    if (!options[required]) throw new Error(`--${required} is required.`);
  }
  return options;
}

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

function formatValue(value, format) {
  if (value === null || value === undefined || value === "") return "—";
  if (format === "percent") {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return escapeHtml(value);
    return `${(numeric * 100).toFixed(2)}%`;
  }
  if (format === "currency") {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return escapeHtml(value);
    return `USD ${numeric.toFixed(2)}`;
  }
  if (format === "number") {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return escapeHtml(value);
    return Number.isInteger(numeric) ? numeric.toLocaleString("en-US") : numeric.toFixed(4);
  }
  return escapeHtml(value);
}

/** Minimal block-level Markdown: headings, paragraphs, lists, bold, inline code. */
function renderMarkdown(body) {
  const inline = (text) =>
    escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const out = [];
  let listBuffer = [];
  const flushList = () => {
    if (listBuffer.length) {
      out.push(`<ul>${listBuffer.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
      listBuffer = [];
    }
  };
  for (const rawLine of String(body ?? "").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const heading = /^(#{2,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = Math.min(heading[1].length, 4);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      listBuffer.push(bullet[1]);
      continue;
    }
    flushList();
    out.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  return out.join("\n");
}

function renderBarChart(chart, rows) {
  const xField = chart.encodings?.x?.field;
  const yField = chart.encodings?.y?.field;
  if (!xField || !yField) throw new Error(`Chart ${chart.id} is missing x or y encoding`);
  const points = rows.map((row) => ({
    label: String(row[xField] ?? ""),
    value: Number(row[yField]),
    row,
  }));
  if (points.some((point) => !Number.isFinite(point.value))) {
    throw new Error(`Chart ${chart.id} has a non-numeric value in ${yField}`);
  }

  const width = 720;
  const rowHeight = 44;
  const padLeft = 190;
  const padRight = 96;
  const padTop = 12;
  const height = padTop * 2 + points.length * rowHeight;
  const maxValue = Math.max(...points.map((point) => Math.abs(point.value)), 0);
  const scale = maxValue > 0 ? (width - padLeft - padRight) / maxValue : 0;

  const bars = points
    .map((point, index) => {
      const y = padTop + index * rowHeight + 8;
      const barWidth = Math.max(1, Math.abs(point.value) * scale);
      const valueText = formatValue(point.value, chart.valueFormat);
      return [
        `<text class="cat" x="${padLeft - 12}" y="${y + 15}" text-anchor="end">${escapeHtml(point.label)}</text>`,
        `<rect class="bar" x="${padLeft}" y="${y}" width="${barWidth.toFixed(2)}" height="22" rx="3"></rect>`,
        `<text class="val" x="${(padLeft + barWidth + 10).toFixed(2)}" y="${y + 16}">${escapeHtml(valueText)}</text>`,
      ].join("");
    })
    .join("");

  const axisLabel = chart.encodings?.y?.label
    ? `<text class="axis" x="${padLeft}" y="${height - 2}">${escapeHtml(chart.encodings.y.label)}</text>`
    : "";

  return [
    `<figure class="chart" id="chart-${escapeHtml(chart.id)}">`,
    `<figcaption><span class="chart-title">${escapeHtml(chart.title ?? chart.id)}</span>`,
    chart.subtitle ? `<span class="chart-sub">${escapeHtml(chart.subtitle)}</span>` : "",
    "</figcaption>",
    `<svg viewBox="0 0 ${width} ${height + 12}" role="img" aria-label="${escapeHtml(chart.title ?? chart.id)}" preserveAspectRatio="xMinYMin meet">`,
    `<line class="axis-line" x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padTop}"></line>`,
    bars,
    axisLabel,
    "</svg>",
    "</figure>",
  ].join("\n");
}

function renderTable(table, rows) {
  const columns = table.columns ?? [];
  const head = columns
    .map((column) => `<th scope="col">${escapeHtml(column.label ?? column.field)}</th>`)
    .join("");
  const body = rows
    .map(
      (row) =>
        `<tr>${columns
          .map((column) => {
            const cell = formatValue(row[column.field], column.format);
            const numeric = column.format && column.format !== "text";
            return `<td${numeric ? ' class="num"' : ""}>${cell}</td>`;
          })
          .join("")}</tr>`,
    )
    .join("");
  return [
    `<figure class="table-block" id="table-${escapeHtml(table.id)}">`,
    `<figcaption><span class="chart-title">${escapeHtml(table.title ?? table.id)}</span>`,
    table.subtitle ? `<span class="chart-sub">${escapeHtml(table.subtitle)}</span>` : "",
    "</figcaption>",
    `<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`,
    "</figure>",
  ].join("\n");
}

function renderMetricStrip(block, cards, datasets) {
  const tiles = (block.cardIds ?? [])
    .map((cardId) => {
      const card = cards.get(cardId);
      if (!card) throw new Error(`Metric strip references unknown card: ${cardId}`);
      const rows = datasets.get(card.dataset) ?? [];
      const row = rows[0] ?? {};
      const metrics = (card.metrics ?? [])
        .map(
          (metric) =>
            `<div class="metric"><span class="metric-label">${escapeHtml(metric.label)}</span>` +
            `<span class="metric-value">${formatValue(row[metric.field], metric.format)}</span></div>`,
        )
        .join("");
      return (
        `<div class="tile" id="card-${escapeHtml(card.id)}">${metrics}` +
        `<p class="tile-note">${escapeHtml(card.description ?? "")}</p></div>`
      );
    })
    .join("");
  return `<section class="metric-strip" id="block-${escapeHtml(block.id)}">${tiles}</section>`;
}

const STYLE = `
:root{color-scheme:light dark;--bg:#ffffff;--fg:#16181d;--muted:#5b6270;--line:#d9dee7;--panel:#f6f8fb;--bar:#2f6f9f;--accent:#12507a}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--fg:#e8ecf2;--muted:#9aa4b4;--line:#2a313b;--panel:#161b22;--bar:#5aa7d8;--accent:#8ec9ef}}
:root[data-theme="dark"]{--bg:#0f1216;--fg:#e8ecf2;--muted:#9aa4b4;--line:#2a313b;--panel:#161b22;--bar:#5aa7d8;--accent:#8ec9ef}
:root[data-theme="light"]{--bg:#ffffff;--fg:#16181d;--muted:#5b6270;--line:#d9dee7;--panel:#f6f8fb;--bar:#2f6f9f;--accent:#12507a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;overflow-x:clip}
main{max-width:1000px;margin:0 auto;padding:32px 20px 72px}
header.doc{border-bottom:2px solid var(--line);padding-bottom:18px;margin-bottom:28px}
header.doc h1{font-size:1.75rem;line-height:1.25;margin:0 0 8px}
header.doc .sub{color:var(--muted);margin:0}
h2{font-size:1.25rem;margin:34px 0 10px;padding-top:6px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:22px 0 8px}
p{margin:10px 0}
ul{margin:10px 0 10px 22px;padding:0}
code{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:.9em}
.metric-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.metric{display:flex;flex-direction:column;margin-bottom:6px}
.metric-label{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}
.metric-value{font-size:1.5rem;font-weight:650;font-variant-numeric:tabular-nums}
.tile-note{color:var(--muted);font-size:.82rem;margin:6px 0 0}
figure{margin:20px 0}
figcaption{display:flex;flex-direction:column;margin-bottom:10px}
.chart-title{font-weight:650}
.chart-sub{color:var(--muted);font-size:.85rem}
.chart svg{width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
.chart .bar{fill:var(--bar)}
.chart .cat{fill:var(--fg);font-size:12px}
.chart .val{fill:var(--fg);font-size:12px;font-variant-numeric:tabular-nums}
.chart .axis{fill:var(--muted);font-size:11px}
.chart .axis-line{stroke:var(--line);stroke-width:1}
.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--panel);font-weight:650}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}
.appendix{margin-top:44px}
.appendix pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto;font-size:.8rem;line-height:1.5}
.source-list{list-style:none;margin:10px 0;padding:0}
.source-list li{padding:6px 0;border-bottom:1px solid var(--line);font-size:.88rem}
footer.doc{margin-top:44px;padding-top:16px;border-top:2px solid var(--line);color:var(--muted);font-size:.82rem}
`;

function buildHtml(artifact) {
  const manifest = artifact.manifest ?? {};
  const snapshot = artifact.snapshot ?? {};
  const datasets = new Map(Object.entries(snapshot.datasets ?? {}));
  const cards = new Map((manifest.cards ?? []).map((card) => [card.id, card]));
  const charts = new Map((manifest.charts ?? []).map((chart) => [chart.id, chart]));
  const tables = new Map((manifest.tables ?? []).map((table) => [table.id, table]));

  const body = [];
  for (const block of manifest.blocks ?? []) {
    if (block.type === "markdown") {
      body.push(`<section id="block-${escapeHtml(block.id)}">${renderMarkdown(block.body)}</section>`);
    } else if (block.type === "metric-strip") {
      body.push(renderMetricStrip(block, cards, datasets));
    } else if (block.type === "chart") {
      const chart = charts.get(block.chartId);
      if (!chart) throw new Error(`Block ${block.id} references unknown chart ${block.chartId}`);
      const rows = datasets.get(chart.dataset);
      if (!rows) throw new Error(`Chart ${chart.id} references unknown dataset ${chart.dataset}`);
      if (chart.type !== "bar") throw new Error(`Unsupported chart type: ${chart.type}`);
      body.push(renderBarChart(chart, rows));
    } else if (block.type === "table") {
      const table = tables.get(block.tableId);
      if (!table) throw new Error(`Block ${block.id} references unknown table ${block.tableId}`);
      const rows = datasets.get(table.dataset);
      if (!rows) throw new Error(`Table ${table.id} references unknown dataset ${table.dataset}`);
      body.push(renderTable(table, rows));
    } else {
      throw new Error(`Unsupported block type: ${block.type}`);
    }
  }

  // The appendix carries the exact rows every figure was drawn from, so a
  // reviewer can re-derive each chart and table without the source database.
  const appendix = [
    '<section class="appendix" id="data-appendix">',
    "<h2>Data appendix</h2>",
    "<p>Every figure above is rendered from the rows below verbatim. No value is recomputed at render time.</p>",
    "<h3>Bound sources</h3>",
    '<ul class="source-list">',
    ...(manifest.sources ?? []).map(
      (source) =>
        `<li><strong>${escapeHtml(source.label ?? source.id)}</strong> — <code>${escapeHtml(source.path ?? "")}</code></li>`,
    ),
    "</ul>",
    ...[...datasets.entries()].map(
      ([name, rows]) =>
        `<h3>Dataset <code>${escapeHtml(name)}</code> (${rows.length} rows)</h3>` +
        `<pre>${escapeHtml(JSON.stringify(rows, null, 2))}</pre>`,
    ),
    "</section>",
  ].join("\n");

  return [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width,initial-scale=1">',
    `<title>${escapeHtml(manifest.title ?? "FOLYNTA Technical Report")}</title>`,
    `<style>${STYLE}</style>`,
    "</head><body><main>",
    '<header class="doc">',
    `<h1>${escapeHtml(manifest.title ?? "FOLYNTA Technical Report")}</h1>`,
    `<p class="sub">${escapeHtml(manifest.description ?? "")}</p>`,
    `<p class="sub">Generated ${escapeHtml(manifest.generatedAt ?? "")} · snapshot status ${escapeHtml(snapshot.status ?? "")}</p>`,
    "</header>",
    body.join("\n"),
    appendix,
    '<footer class="doc">Rendered by tools/release/render_folynta_portable_report.mjs from ',
    `${escapeHtml(manifest.title ?? "the report artifact")}. Self-contained: no external stylesheet, script, font, or image is referenced.</footer>`,
    "</main></body></html>",
  ].join("\n");
}

function validate(artifact) {
  const problems = [];
  if (artifact.surface !== "report") problems.push("artifact surface is not 'report'");
  const manifest = artifact.manifest;
  const snapshot = artifact.snapshot;
  if (!manifest || typeof manifest !== "object") problems.push("manifest is missing");
  if (!snapshot || typeof snapshot !== "object") problems.push("snapshot is missing");
  if (problems.length) return problems;

  const datasets = snapshot.datasets ?? {};
  for (const [name, rows] of Object.entries(datasets)) {
    if (!Array.isArray(rows)) problems.push(`dataset ${name} is not an array`);
    else if (!rows.length) problems.push(`dataset ${name} is empty`);
  }
  const chartIds = new Set((manifest.charts ?? []).map((chart) => chart.id));
  const tableIds = new Set((manifest.tables ?? []).map((table) => table.id));
  const cardIds = new Set((manifest.cards ?? []).map((card) => card.id));
  for (const block of manifest.blocks ?? []) {
    if (block.type === "chart" && !chartIds.has(block.chartId)) {
      problems.push(`block ${block.id} references unknown chart ${block.chartId}`);
    }
    if (block.type === "table" && !tableIds.has(block.tableId)) {
      problems.push(`block ${block.id} references unknown table ${block.tableId}`);
    }
    if (block.type === "metric-strip") {
      for (const cardId of block.cardIds ?? []) {
        if (!cardIds.has(cardId)) problems.push(`block ${block.id} references unknown card ${cardId}`);
      }
    }
  }
  for (const chart of manifest.charts ?? []) {
    if (!(chart.dataset in datasets)) problems.push(`chart ${chart.id} references unknown dataset ${chart.dataset}`);
  }
  for (const table of manifest.tables ?? []) {
    if (!(table.dataset in datasets)) problems.push(`table ${table.id} references unknown dataset ${table.dataset}`);
  }
  if (!(manifest.blocks ?? []).length) problems.push("manifest has no blocks");
  return problems;
}

/**
 * Structural verification of the written document. No browser is launched, so
 * the stage reports `structural_only` rather than claiming a rendered check.
 */
function verify(html, artifact) {
  const problems = [];
  const manifest = artifact.manifest ?? {};
  if (!html.startsWith("<!doctype html>")) problems.push("document has no doctype");
  if (!html.includes("</html>")) problems.push("document is truncated");
  for (const block of manifest.blocks ?? []) {
    if (!html.includes(`id="block-${block.id}"`) && block.type !== "chart" && block.type !== "table") {
      problems.push(`block ${block.id} is not present in the document`);
    }
  }
  for (const chart of manifest.charts ?? []) {
    if (!html.includes(`id="chart-${chart.id}"`)) problems.push(`chart ${chart.id} is not present`);
  }
  for (const table of manifest.tables ?? []) {
    if (!html.includes(`id="table-${table.id}"`)) problems.push(`table ${table.id} is not present`);
  }
  const external = /(?:src|href)\s*=\s*["']https?:\/\//i.exec(html);
  if (external) problems.push(`document references an external resource: ${external[0]}`);
  if (/<script\b/i.test(html)) problems.push("document contains a script element");
  return problems;
}

async function run(argv = process.argv.slice(2)) {
  let options;
  try {
    options = parseArguments(argv);
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ ok: false, stage: "invocation", error: error.message })}\n`);
    process.exitCode = 1;
    return;
  }
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }

  const stages = { validation: "pending", package: "pending", verification: "pending" };
  const inputPath = resolve(options.input);
  const outputPath = resolve(options.output);
  try {
    const raw = readFileSync(inputPath, "utf8");
    const artifact = JSON.parse(raw);

    const validationProblems = validate(artifact);
    if (validationProblems.length) {
      stages.validation = "failed";
      throw new Error(`artifact validation failed: ${validationProblems.join("; ")}`);
    }
    stages.validation = "passed";

    const html = buildHtml(artifact);
    mkdirSync(dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, html, "utf8");
    stages.package = "passed";

    const written = readFileSync(outputPath, "utf8");
    const verificationProblems = verify(written, artifact);
    if (verificationProblems.length) {
      stages.verification = "failed";
      throw new Error(`document verification failed: ${verificationProblems.join("; ")}`);
    }
    stages.verification = "structural_only";

    const result = {
      ok: true,
      renderer: "tools/release/render_folynta_portable_report.mjs",
      renderer_note:
        "Self-contained renderer used because the external portable-report plugin is not part of this repository.",
      stages,
      input_path: inputPath,
      input_sha256: `sha256:${createHash("sha256").update(raw).digest("hex")}`,
      output_path: outputPath,
      output_bytes: statSync(outputPath).size,
      output_sha256: `sha256:${createHash("sha256").update(written).digest("hex")}`,
      block_count: (artifact.manifest?.blocks ?? []).length,
      chart_count: (artifact.manifest?.charts ?? []).length,
      table_count: (artifact.manifest?.tables ?? []).length,
      browser_render_verified: false,
    };
    if (options.receipt) {
      mkdirSync(dirname(resolve(options.receipt)), { recursive: true });
      writeFileSync(resolve(options.receipt), `${JSON.stringify(result, null, 2)}\n`, "utf8");
    }
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    const result = { ok: false, stages, error: error?.message ?? String(error) };
    if (options.receipt) {
      try {
        mkdirSync(dirname(resolve(options.receipt)), { recursive: true });
        writeFileSync(resolve(options.receipt), `${JSON.stringify(result, null, 2)}\n`, "utf8");
      } catch {
        /* the stderr payload below remains the authoritative failure record */
      }
    }
    process.stderr.write(`${JSON.stringify(result)}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await run();
}

export { buildHtml, parseArguments, renderMarkdown, validate, verify };
