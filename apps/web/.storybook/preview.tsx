import type { Preview } from "@storybook/nextjs-vite";

import "../src/app/globals.css";
import "../public/styles/structara.css";

const preview: Preview = {
  parameters: {
    a11y: {
      config: {
        rules: [
          { id: "color-contrast", enabled: true },
          { id: "focus-order-semantics", enabled: true },
        ],
      },
      test: "error",
    },
    controls: {
      expanded: true,
      sort: "requiredFirst",
    },
    layout: "fullscreen",
    options: {
      storySort: {
        order: ["System", "Product", "Brand"],
      },
    },
  },
  decorators: [
    (Story) => (
      <div
        style={{
          minHeight: "100vh",
          padding: "clamp(1rem, 3vw, 3rem)",
          background: "var(--st-canvas, #f4f2ec)",
          color: "var(--st-ink, #151714)",
        }}
      >
        <Story />
      </div>
    ),
  ],
};

export default preview;
