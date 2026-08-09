/**
 * Affordance integrity checker — DESIGN_MASTER_V3 §14.3.
 *
 * Every element that looks interactive must be one of:
 *   1. actually wired,
 *   2. disabled, with a reason and a "available when" note,
 *   3. a plain label with no button semantics,
 *   4. removed.
 *
 * The original version only looked at <button> and only asked whether one of
 * onClick / type=submit / formAction / a spread was present. §14.3 widens it to
 * six more checks; each is implemented below and tagged with its rule id so a
 * finding says which contract broke.
 */
import fs from "node:fs";
import path from "node:path";

import ts from "typescript";

const sourceRoot = path.resolve("src");
const appRoot = path.join(sourceRoot, "app");

const RULES = {
  DEAD_BUTTON: "dead-button",
  DEAD_ROLE_BUTTON: "dead-role-button",
  EMPTY_HANDLER: "empty-handler",
  PREVENT_DEFAULT_ONLY: "prevent-default-only",
  FOCUS_ONLY: "focus-only",
  BROKEN_LINK: "broken-link",
  DISABLED_WITHOUT_NAME: "disabled-without-name",
  DISABLED_WITHOUT_REASON: "disabled-without-reason",
};

/**
 * §14.3 clause 2 wants a disabled control to state the reason and when it
 * becomes available. Whether prose actually says that is not decidable from the
 * AST, so `disabled-without-reason` reports the controls that carry no
 * explanatory attribute at all and stays advisory: it prints, it does not fail
 * the build. Everything else is blocking. W7 converts the app shell and is
 * where these get their reasons; flipping this to blocking is a one-line change
 * here once that lands.
 */
const ADVISORY_RULES = new Set([RULES.DISABLED_WITHOUT_REASON]);

const NATIVE_FORM_CONTROLS = new Set([
  "button",
  "input",
  "select",
  "textarea",
  "fieldset",
  "option",
]);

// The HTML drag-and-drop model requires preventDefault on dragover/dragenter
// for a drop target to accept a drop, so those handlers are legitimately
// nothing but preventDefault.
const DRAG_HANDLERS = new Set(["onDragOver", "onDragEnter"]);

const findings = [];
const routes = collectRoutes();

const files = walk(sourceRoot).filter((candidate) => candidate.endsWith(".tsx"));

for (const filePath of files) {
  const sourceText = fs.readFileSync(filePath, "utf8");
  const sourceFile = ts.createSourceFile(
    filePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  visit(sourceFile, sourceFile);
}

report();

// ── traversal ───────────────────────────────────────────────────────────────

function visit(node, sourceFile) {
  if (ts.isJsxElement(node)) inspect(node.openingElement, sourceFile, node);
  if (ts.isJsxSelfClosingElement(node)) inspect(node, sourceFile, node);
  ts.forEachChild(node, (child) => visit(child, sourceFile));
}

function inspect(openingElement, sourceFile, element) {
  const tagName = openingElement.tagName.getText(sourceFile);
  const attributes = readAttributes(openingElement, sourceFile);
  const isNativeButton = tagName === "button";
  const isAnchor = tagName === "a" || tagName === "Link";
  const isRoleButton = attributes.strings.role === "button";

  if (isNativeButton) checkButton(attributes, sourceFile, openingElement);
  if (isRoleButton && !isNativeButton) {
    checkRoleButton(attributes, sourceFile, openingElement, tagName);
  }
  if (isAnchor) checkAnchor(attributes, sourceFile, openingElement);
  checkFocusOnly(attributes, sourceFile, openingElement, tagName);
  checkHandlers(attributes, sourceFile, openingElement, tagName);
  if (attributes.names.has("disabled") && NATIVE_FORM_CONTROLS.has(tagName)) {
    checkDisabledExplanation(attributes, sourceFile, openingElement, element);
  }
}

// ── individual contracts ────────────────────────────────────────────────────

function checkButton(attributes, sourceFile, openingElement) {
  if (attributes.hasSpread) return;
  if (attributes.names.has("disabled")) return;
  if (
    attributes.names.has("onClick") ||
    attributes.names.has("formAction") ||
    attributes.strings.type === "submit"
  ) {
    return;
  }
  push(
    RULES.DEAD_BUTTON,
    sourceFile,
    openingElement,
    "enabled <button> with no onClick, submit, formAction, or spread contract",
  );
}

function checkRoleButton(attributes, sourceFile, openingElement, tagName) {
  if (attributes.hasSpread) return;
  if (attributes.names.has("onClick") || attributes.names.has("href")) return;
  push(
    RULES.DEAD_ROLE_BUTTON,
    sourceFile,
    openingElement,
    `<${tagName} role="button"> with no onClick or href`,
  );
}

function checkAnchor(attributes, sourceFile, openingElement) {
  const href = attributes.strings.href;
  if (href === undefined) return; // computed href — out of static reach
  if (!href.startsWith("/")) return; // external, mailto:, tel:, or #anchor
  const target = href.split("?")[0].split("#")[0].replace(/\/$/, "") || "/";
  if (routes.has(target)) return;
  if (matchesDynamicRoute(target)) return;
  push(
    RULES.BROKEN_LINK,
    sourceFile,
    openingElement,
    `href "${href}" does not resolve to a route or a PUBLIC_PAGES entry`,
  );
}

function checkFocusOnly(attributes, sourceFile, openingElement, tagName) {
  if (!attributes.names.has("tabIndex")) return;
  if (attributes.hasSpread) return;
  // tabIndex={-1} is the standard way to mark a programmatic focus target — a
  // dialog, a skip-link landing, a heading focused after navigation. It is
  // deliberately not in the tab order, so it is not a dead affordance. Only a
  // control the user can tab to has to do something.
  if ((attributes.numbers.tabIndex ?? -1) < 0) return;
  // An explicit role plus a name is a declared widget or region, not a stray
  // focus stop. A scrollable table region, for one, has to be tabbable to
  // satisfy WCAG 2.1.1 even though it has no handler of its own.
  if (attributes.strings.role && attributes.names.has("aria-label")) return;
  const interactive =
    tagName === "button" ||
    tagName === "a" ||
    tagName === "Link" ||
    tagName === "input" ||
    tagName === "select" ||
    tagName === "textarea";
  if (interactive) return;
  const wired = [...attributes.names].some((name) => name.startsWith("on"));
  if (wired) return;
  push(
    RULES.FOCUS_ONLY,
    sourceFile,
    openingElement,
    `<${tagName}> is reachable by tab (tabIndex=${attributes.numbers.tabIndex}) but has no handler`,
  );
}

function checkHandlers(attributes, sourceFile, openingElement, tagName) {
  for (const [name, handler] of Object.entries(attributes.handlers)) {
    const body = handlerBody(handler);
    if (body === null) continue;
    if (isEmptyBody(body)) {
      push(
        RULES.EMPTY_HANDLER,
        sourceFile,
        openingElement,
        `<${tagName} ${name}> is an empty callback`,
      );
      continue;
    }
    if (DRAG_HANDLERS.has(name)) continue;
    if (isPreventDefaultOnly(body, sourceFile)) {
      push(
        RULES.PREVENT_DEFAULT_ONLY,
        sourceFile,
        openingElement,
        `<${tagName} ${name}> only calls preventDefault`,
      );
    }
  }
}

function checkDisabledExplanation(
  attributes,
  sourceFile,
  openingElement,
  element,
) {
  const named =
    attributes.names.has("aria-label") ||
    attributes.names.has("aria-labelledby") ||
    attributes.names.has("title") ||
    hasContent(element);

  // Only <button> is checked for a name here. Form fields get theirs from a
  // wrapping or associated <label>, which is not visible from this node, and
  // the axe pass in e2e/workspace.spec.ts already fails on an unnamed field.
  if (!named && openingElement.tagName.getText(sourceFile) === "button") {
    push(
      RULES.DISABLED_WITHOUT_NAME,
      sourceFile,
      openingElement,
      "disabled control has no accessible name at all",
    );
    return;
  }

  const explained =
    attributes.names.has("title") ||
    attributes.names.has("aria-describedby") ||
    attributes.names.has("data-disabled-reason") ||
    attributes.names.has("data-sample-static-control");
  if (explained) return;
  push(
    RULES.DISABLED_WITHOUT_REASON,
    sourceFile,
    openingElement,
    "disabled control carries no reason and no availability note (§14.3 clause 2)",
  );
}

// ── route resolution ────────────────────────────────────────────────────────

function collectRoutes() {
  const found = new Set(["/"]);

  // 1. the src/app route tree
  if (fs.existsSync(appRoot)) {
    for (const file of walk(appRoot)) {
      const base = path.basename(file);
      if (base !== "page.tsx" && base !== "route.ts") continue;
      const relative = path
        .relative(appRoot, path.dirname(file))
        .split(path.sep)
        .filter((segment) => !(segment.startsWith("(") && segment.endsWith(")")))
        .join("/");
      found.add(relative ? `/${relative}` : "/");
    }
  }

  // 2. PUBLIC_PAGES. The catch-all route calls notFound() for anything absent
  //    from this map, so the map — not the catch-all — is what makes a
  //    marketing path real. Entries are built by page("/product", …) calls, so
  //    the first string argument is the path.
  const contentFile = path.join(sourceRoot, "lib", "tavonel-content.ts");
  if (fs.existsSync(contentFile)) {
    const text = fs.readFileSync(contentFile, "utf8");
    const source = ts.createSourceFile(
      contentFile,
      text,
      ts.ScriptTarget.Latest,
      true,
    );
    const collect = (node) => {
      if (
        ts.isCallExpression(node) &&
        node.expression.getText(source) === "page" &&
        node.arguments.length > 0 &&
        ts.isStringLiteral(node.arguments[0]) &&
        node.arguments[0].text.startsWith("/")
      ) {
        found.add(node.arguments[0].text);
      }
      if (
        ts.isPropertyAssignment(node) &&
        ts.isStringLiteral(node.name) &&
        node.name.text.startsWith("/")
      ) {
        found.add(node.name.text);
      }
      ts.forEachChild(node, collect);
    };
    collect(source);
  }

  return found;
}

function matchesDynamicRoute(target) {
  const segments = target.split("/").filter(Boolean);
  for (const route of routes) {
    const routeSegments = route.split("/").filter(Boolean);
    // Catch-all segments are skipped on purpose. Treating [...slug] as a match
    // for everything would make this rule accept every href, which is how a
    // 404-target check quietly becomes a no-op.
    if (
      routeSegments.some(
        (segment) => segment.startsWith("[...") || segment.startsWith("[[..."),
      )
    ) {
      continue;
    }
    if (routeSegments.length !== segments.length) continue;
    let matched = true;
    for (const [index, segment] of routeSegments.entries()) {
      if (segment.startsWith("[")) continue; // [id] matches one segment
      if (segment !== segments[index]) {
        matched = false;
        break;
      }
    }
    if (matched) return true;
  }
  return false;
}

// ── AST helpers ─────────────────────────────────────────────────────────────

function readAttributes(openingElement, sourceFile) {
  const names = new Set();
  const strings = {};
  const numbers = {};
  const handlers = {};
  let hasSpread = false;

  for (const attribute of openingElement.attributes.properties) {
    if (ts.isJsxSpreadAttribute(attribute)) {
      hasSpread = true;
      continue;
    }
    const name = attribute.name.getText(sourceFile);
    names.add(name);

    const initializer = attribute.initializer;
    if (!initializer) continue;
    if (ts.isStringLiteral(initializer)) {
      strings[name] = initializer.text;
    } else if (ts.isJsxExpression(initializer) && initializer.expression) {
      const expression = initializer.expression;
      if (ts.isStringLiteral(expression)) strings[name] = expression.text;
      const numeric = numericValue(expression);
      if (numeric !== null) numbers[name] = numeric;
      if (name.startsWith("on")) handlers[name] = expression;
    }
  }

  return { names, strings, numbers, handlers, hasSpread };
}

function numericValue(expression) {
  if (ts.isNumericLiteral(expression)) return Number(expression.text);
  if (
    ts.isPrefixUnaryExpression(expression) &&
    expression.operator === ts.SyntaxKind.MinusToken &&
    ts.isNumericLiteral(expression.operand)
  ) {
    return -Number(expression.operand.text);
  }
  return null;
}

/** Any rendered child — text, an expression, or a nested element. */
function hasContent(element) {
  if (!ts.isJsxElement(element)) return false;
  return element.children.some((child) => {
    if (ts.isJsxText(child)) return child.text.trim().length > 0;
    if (ts.isJsxExpression(child)) return Boolean(child.expression);
    return true;
  });
}

function handlerBody(expression) {
  if (ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) {
    return expression.body;
  }
  return null;
}

function isEmptyBody(body) {
  if (ts.isBlock(body)) return body.statements.length === 0;
  return false;
}

function isPreventDefaultOnly(body, sourceFile) {
  const statements = ts.isBlock(body) ? [...body.statements] : [body];
  if (statements.length === 0) return false;
  return statements.every((statement) => {
    const expression = ts.isExpressionStatement(statement)
      ? statement.expression
      : statement;
    if (!expression || !ts.isCallExpression(expression)) return false;
    const callee = expression.expression.getText(sourceFile);
    return (
      callee.endsWith(".preventDefault") || callee.endsWith(".stopPropagation")
    );
  });
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const candidate = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(candidate) : [candidate];
  });
}

function push(rule, sourceFile, node, message) {
  const location = sourceFile.getLineAndCharacterOfPosition(
    node.getStart(sourceFile),
  );
  findings.push({
    rule,
    location: `${path.relative(process.cwd(), sourceFile.fileName)}:${location.line + 1}`,
    message,
  });
}

function report() {
  const blocking = findings.filter((finding) => !ADVISORY_RULES.has(finding.rule));
  const advisory = findings.filter((finding) => ADVISORY_RULES.has(finding.rule));

  if (advisory.length > 0) {
    console.log(
      `\nAdvisory — ${advisory.length} disabled control(s) give no reason and no availability note (§14.3 clause 2). Not blocking; W7 owns the app-shell conversion.`,
    );
    for (const entry of groupByFile(advisory)) console.log(`    ${entry}`);
  }

  if (blocking.length === 0) {
    console.log(
      `TAVONEL affordance contracts verified — ${files.length} files, ${routes.size} known routes, 0 blocking findings.`,
    );
    return;
  }

  console.error(
    `\nTAVONEL affordance contracts failed — ${blocking.length} blocking finding(s). §14.3: every interactive-looking element must work, be disabled with a reason, be a plain label, or be removed.`,
  );
  const byRule = new Map();
  for (const finding of blocking) {
    if (!byRule.has(finding.rule)) byRule.set(finding.rule, []);
    byRule.get(finding.rule).push(finding);
  }
  for (const [rule, entries] of byRule) {
    console.error(`\n  [${rule}] ${entries.length}`);
    for (const entry of entries) {
      console.error(`    ${entry.location}  ${entry.message}`);
    }
  }
  process.exit(1);
}

function groupByFile(entries) {
  const counts = new Map();
  for (const entry of entries) {
    const file = entry.location.split(":")[0];
    counts.set(file, (counts.get(file) ?? 0) + 1);
  }
  return [...counts]
    .sort((a, b) => b[1] - a[1])
    .map(([file, count]) => `${String(count).padStart(3)}  ${file}`);
}
