import { BracketsCurly, FileText } from "@phosphor-icons/react/dist/ssr";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand" aria-label="AI Knowledge Compiler">
      <span className="brand-mark" aria-hidden="true">
        <FileText size={18} weight="fill" />
        <BracketsCurly className="brand-code" size={11} weight="bold" />
      </span>
      {!compact && (
        <span className="brand-copy">
          <span>Knowledge Compiler</span>
          <small>Evidence-first workspace</small>
        </span>
      )}
    </span>
  );
}
