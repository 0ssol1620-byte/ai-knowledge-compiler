import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { BrandMark } from "@/components/brand-mark";
import {
  TavonelGlyph,
  type TavonelGlyphName,
} from "@/components/tavonel-glyph";

const GLYPHS: TavonelGlyphName[] = [
  "page",
  "block",
  "table",
  "evidence",
  "verified",
  "note",
  "node",
  "branch",
  "formula",
  "figure",
  "relation",
  "perspective",
  "timeline",
  "package",
  "api",
  "policy",
  "audit",
  "review",
];

function BrandSystem({ compact = false }: { compact?: boolean }) {
  return (
    <section style={{ display: "grid", gap: "2rem" }}>
      <BrandMark compact={compact} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))",
          gap: "1rem",
        }}
      >
        {GLYPHS.map((glyph) => (
          <figure
            key={glyph}
            style={{ margin: 0, display: "grid", gap: ".5rem" }}
          >
            <TavonelGlyph name={glyph} size={32} label={`${glyph} glyph`} />
            <figcaption>{glyph}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

const meta = {
  title: "Brand/Mark and semantic glyphs",
  component: BrandSystem,
  args: { compact: false },
  tags: ["autodocs"],
} satisfies Meta<typeof BrandSystem>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FullMark: Story = {};
export const CompactMark: Story = { args: { compact: true } };
