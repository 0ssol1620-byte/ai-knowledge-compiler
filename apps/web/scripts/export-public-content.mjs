import fs from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);

const sourcePath = new URL("../src/lib/structara-content.ts", import.meta.url);
const source = fs.readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
  fileName: "structara-content.ts",
}).outputText;
const runtimeModule = { exports: {} };
const context = vm.createContext({
  module: runtimeModule,
  exports: runtimeModule.exports,
  require,
  console,
});
vm.runInContext(transpiled, context, { filename: "structara-content.cjs" });
const pages = runtimeModule.exports.PUBLIC_PAGES;
const outputPath = new URL("../../../work/public-pages-en.json", import.meta.url);
fs.mkdirSync(new URL("../../../work/", import.meta.url), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(pages, null, 2) + "\n");
console.log(`exported ${Object.keys(pages).length} pages to ${outputPath.pathname}`);
