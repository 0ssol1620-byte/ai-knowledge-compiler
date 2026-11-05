import type { StorybookConfig } from "@storybook/react-vite";
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../src", import.meta.url));
const contractsSource = fileURLToPath(
  new URL("../../../packages/contracts/src/generated-contracts.ts", import.meta.url),
);

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"],
  addons: ["@storybook/addon-docs", "@storybook/addon-a11y"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  staticDirs: ["../public"],
  env: (current) => ({
    ...current,
    NEXT_PUBLIC_AKC_DEMO_MODE: "true",
  }),
  viteFinal: async (viteConfig) => {
    viteConfig.resolve ??= {};
    const aliases = viteConfig.resolve.alias ?? {};
    viteConfig.resolve.alias = Array.isArray(aliases)
      ? [
          ...aliases,
          { find: "@akc/contracts", replacement: contractsSource },
          { find: "@", replacement: sourceRoot },
        ]
      : {
          ...aliases,
          "@akc/contracts": contractsSource,
          "@": sourceRoot,
        };
    return viteConfig;
  },
};

export default config;
