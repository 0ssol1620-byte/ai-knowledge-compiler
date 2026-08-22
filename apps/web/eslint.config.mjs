import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
    },
  },
  globalIgnores([
    ".next/**",
    ".next-e2e-live/**",
    ".next-*/**",
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
    // The PDF.js worker is a vendored, minified third-party bundle served as a
    // static asset. It is not ours to change, and linting it produced 1,576 of
    // the 1,578 findings in this app.
    "public/proof-sources/pdf.worker-*.min.mjs",
  ]),
]);
