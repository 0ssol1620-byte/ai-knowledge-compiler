export type TavonelGlyphName =
  | "page"
  | "block"
  | "table"
  | "evidence"
  | "verified"
  | "note"
  | "node"
  | "branch"
  | "formula"
  | "figure"
  | "relation"
  | "perspective"
  | "timeline"
  | "package"
  | "api"
  | "policy"
  | "audit"
  | "review";

export function TavonelGlyph({
  name,
  size = 24,
  label,
}: {
  name: TavonelGlyphName;
  size?: number;
  label?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden={label ? undefined : "true"}
      aria-label={label}
      role={label ? "img" : undefined}
      focusable="false"
    >
      <use href={`/brand/tavonel-glyphs.svg#${name}`} />
    </svg>
  );
}
