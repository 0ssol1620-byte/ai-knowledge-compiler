import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { CoreComponentShowcase, coreComponentStyles } from "./core-components";

const meta = {
  title: "System/Core component contract",
  component: CoreComponentShowcase,
  parameters: {
    docs: {
      description: {
        component:
          "Release-bound state coverage for Structara buttons, distinct status/origin badges, surfaces, and system feedback.",
      },
    },
  },
  args: {
    density: "comfortable",
    locale: "en",
    motion: "full",
    state: "default",
  },
  argTypes: {
    density: { control: "inline-radio", options: ["compact", "comfortable"] },
    locale: { control: "inline-radio", options: ["en", "ko"] },
    motion: { control: "inline-radio", options: ["full", "reduced"] },
    state: {
      control: "select",
      options: ["default", "hover", "focus", "loading", "empty", "error"],
    },
  },
  tags: ["autodocs"],
} satisfies Meta<typeof CoreComponentShowcase>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Hover: Story = { args: { state: "hover" } };
export const Focus: Story = { args: { state: "focus" } };
export const Loading: Story = { args: { state: "loading" } };
export const LoadingKorean: Story = {
  args: { locale: "ko", state: "loading" },
};
export const Empty: Story = { args: { state: "empty" } };
export const EmptyKorean: Story = { args: { locale: "ko", state: "empty" } };
export const Error: Story = { args: { state: "error" } };
export const ErrorKorean: Story = { args: { locale: "ko", state: "error" } };
export const LongKorean: Story = { args: { locale: "ko" } };
export const LongEnglish: Story = { args: { locale: "en" } };
export const Compact: Story = { args: { density: "compact" } };
export const Comfortable: Story = { args: { density: "comfortable" } };
export const Mobile: Story = {
  decorators: [
    (Story) => (
      <div className={coreComponentStyles.mobileFrame}>
        <Story />
      </div>
    ),
  ],
  parameters: { viewport: { defaultViewport: "mobile1" } },
};
export const MobileKorean: Story = {
  args: { locale: "ko" },
  decorators: Mobile.decorators,
  parameters: Mobile.parameters,
};
export const ReducedMotion: Story = {
  args: { motion: "reduced", state: "hover" },
};
export const ReducedMotionLoading: Story = {
  args: { motion: "reduced", state: "loading" },
};
