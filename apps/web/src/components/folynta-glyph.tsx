export type FolyntaGlyphName =
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

export function FolyntaGlyph({
  name,
  size = 24,
  label,
}: {
  name: FolyntaGlyphName;
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
      <use href={`/brand/folynta-glyphs.svg#${name}`} />
    </svg>
  );
}
