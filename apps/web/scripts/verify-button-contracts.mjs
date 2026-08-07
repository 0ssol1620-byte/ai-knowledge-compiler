import fs from "node:fs";
import path from "node:path";

import ts from "typescript";

const sourceRoot = path.resolve("src");
const findings = [];

for (const filePath of walk(sourceRoot).filter((candidate) =>
  candidate.endsWith(".tsx"),
)) {
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

if (findings.length > 0) {
  console.error(
    "Enabled buttons must define onClick, submit, formAction, disabled, or an explicit spread-prop contract.",
  );
  for (const finding of findings) console.error(`- ${finding}`);
  process.exit(1);
}

console.log("FOLYNTA button contracts verified (0 enabled dead controls).");

function visit(node, sourceFile) {
  if (ts.isJsxElement(node)) checkButton(node.openingElement, sourceFile);
  if (ts.isJsxSelfClosingElement(node)) checkButton(node, sourceFile);
  ts.forEachChild(node, (child) => visit(child, sourceFile));
}

function checkButton(openingElement, sourceFile) {
  if (openingElement.tagName.getText(sourceFile) !== "button") return;

  const attributeNames = new Set();
  let hasSpread = false;
  let type = "";

  for (const attribute of openingElement.attributes.properties) {
    if (ts.isJsxSpreadAttribute(attribute)) {
      hasSpread = true;
      continue;
    }

    const name = attribute.name.getText(sourceFile);
    attributeNames.add(name);
    if (
      name === "type" &&
      attribute.initializer &&
      ts.isStringLiteral(attribute.initializer)
    ) {
      type = attribute.initializer.text;
    }
  }

  if (
    hasSpread ||
    attributeNames.has("onClick") ||
    attributeNames.has("disabled") ||
    attributeNames.has("formAction") ||
    type === "submit"
  ) {
    return;
  }

  const location = sourceFile.getLineAndCharacterOfPosition(
    openingElement.getStart(sourceFile),
  );
  findings.push(
    `${path.relative(process.cwd(), sourceFile.fileName)}:${location.line + 1}`,
  );
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const candidate = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(candidate) : [candidate];
  });
}
