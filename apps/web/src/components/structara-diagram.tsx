import { StructaraGlyph } from "@/components/structara-glyph";
import type { StructaraGlyphName } from "@/components/structara-glyph";
import {
  STRUCTARA_DIAGRAMS,
  type StructaraDiagramId,
} from "@/lib/structara-diagrams";

const diagramGlyphs: StructaraGlyphName[] = [
  "page",
  "block",
  "evidence",
  "node",
];

export function StructaraDiagram({ id }: { id: StructaraDiagramId }) {
  const diagram = STRUCTARA_DIAGRAMS[id];

  return (
    <figure className="st-architecture-diagram" aria-labelledby={`${id}-title`}>
      <figcaption>
        <span>System diagram · deterministic</span>
        <h2 id={`${id}-title`}>{diagram.title}</h2>
        <p>{diagram.question}</p>
      </figcaption>
      <div className="st-diagram-canvas" aria-hidden="true">
        <svg viewBox="0 0 960 280" preserveAspectRatio="none">
          <path d="M120 140H840" />
          <path d="M275 140l-18-12v24zM495 140l-18-12v24zM715 140l-18-12v24z" />
        </svg>
        {diagram.nodes.map((node, index) => (
          <div key={node}>
            <StructaraGlyph name={diagramGlyphs[index]!} size={22} />
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{node}</strong>
          </div>
        ))}
      </div>
      <ol className="st-diagram-equivalent">
        {diagram.nodes.map((node) => (
          <li key={node}>{node}</li>
        ))}
      </ol>
    </figure>
  );
}
