export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand fl-brand" aria-label="FOLYNTA">
      <span className="fl-brand-glyph" aria-hidden="true">
        <span />
        <span />
        <i />
      </span>
      {!compact && (
        <span className="brand-copy fl-brand-copy">
          <span>FOLYNTA</span>
          <small>Knowledge Compiler</small>
        </span>
      )}
    </span>
  );
}
