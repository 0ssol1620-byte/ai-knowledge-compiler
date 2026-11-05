import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import {
  SignatureAssetComposition,
  type CompositionDirection,
  type SignatureAssetId,
} from "@/components/system/signature-asset-compositions";

const meta = {
  title: "Brand/Signature assets/18 direction matrix",
  component: SignatureAssetComposition,
  args: { asset: "A01", direction: "A" },
  argTypes: {
    asset: { control: "select", options: ["A01", "A02", "A03", "A04", "A05", "A06"] },
    direction: { control: "inline-radio", options: ["A", "B", "C"] },
  },
  parameters: { layout: "fullscreen" },
  tags: ["autodocs", "deterministic-dom", "truth-boundary"],
} satisfies Meta<typeof SignatureAssetComposition>;

export default meta;
type Story = StoryObj<typeof meta>;

function composition(asset: SignatureAssetId, direction: CompositionDirection): Story {
  return { args: { asset, direction } };
}

export const A01DirectionA: Story = composition("A01", "A");
export const A01DirectionB: Story = composition("A01", "B");
export const A01DirectionC: Story = composition("A01", "C");
export const A02DirectionA: Story = composition("A02", "A");
export const A02DirectionB: Story = composition("A02", "B");
export const A02DirectionC: Story = composition("A02", "C");
export const A03DirectionA: Story = composition("A03", "A");
export const A03DirectionB: Story = composition("A03", "B");
export const A03DirectionC: Story = composition("A03", "C");
export const A04DirectionA: Story = composition("A04", "A");
export const A04DirectionB: Story = composition("A04", "B");
export const A04DirectionC: Story = composition("A04", "C");
export const A05DirectionA: Story = composition("A05", "A");
export const A05DirectionB: Story = composition("A05", "B");
export const A05DirectionC: Story = composition("A05", "C");
export const A06DirectionA: Story = composition("A06", "A");
export const A06DirectionB: Story = composition("A06", "B");
export const A06DirectionC: Story = composition("A06", "C");
