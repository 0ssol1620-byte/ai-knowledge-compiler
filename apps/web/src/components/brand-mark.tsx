import { PUBLIC_BRAND } from "@/lib/brand";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand st-brand" aria-label={PUBLIC_BRAND.name}>
      <span className="st-brand-glyph" aria-hidden="true">
        <span />
        <span />
        <i />
      </span>
      {!compact && (
        <span className="brand-copy st-brand-copy">
          <span>{PUBLIC_BRAND.name}</span>
          <small>{PUBLIC_BRAND.category}</small>
        </span>
      )}
    </span>
  );
}
