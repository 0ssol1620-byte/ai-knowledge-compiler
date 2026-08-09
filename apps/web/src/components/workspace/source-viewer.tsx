"use client";

import {
  ArrowsIn,
  ArrowsOut,
  ArrowClockwise,
  Eye,
  EyeSlash,
  FileText,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";

import { bboxStyle } from "@/lib/bbox";
import { apiAbsoluteUrl } from "@/lib/api-client";
import type { CanonicalBlock, PageSummary, SourceRef } from "@/lib/types";

export function SourceViewer({
  page,
  selectedBlockId,
  onSelectBlock,
  highlightedEvidence,
  onEvidenceInteraction,
  sample = false,
}: {
  page: PageSummary;
  selectedBlockId?: string;
  onSelectBlock: (blockId: string) => void;
  highlightedEvidence?: { blockId: string; source: SourceRef } | null;
  onEvidenceInteraction?: (
    blockId: string,
    source: SourceRef,
    action: "focus" | "blur" | "select",
  ) => void;
  sample?: boolean;
}) {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [rawTextVisible, setRawTextVisible] = useState(false);
  const [fullscreenMode, setFullscreenMode] = useState<
    "none" | "native" | "fallback"
  >("none");
  const panelRef = useRef<HTMLElement>(null);
  const blocks = useMemo(
    () =>
      page.blocks.length > 0
        ? page.blocks
        : sample
          ? fallbackBlocks(page.page_number)
          : [],
    [page, sample],
  );
  const rawBlocks = useMemo(
    () =>
      blocks.filter(
        (block) =>
          Boolean(block.source_text.trim()) &&
          Boolean(block.source_refs[0]?.bbox1000),
      ),
    [blocks],
  );
  const fullscreen = fullscreenMode !== "none";

  useEffect(() => {
    function syncFullscreenState() {
      setFullscreenMode((current) => {
        if (document.fullscreenElement === panelRef.current) return "native";
        return current === "native" ? "none" : current;
      });
    }

    document.addEventListener("fullscreenchange", syncFullscreenState);
    return () =>
      document.removeEventListener("fullscreenchange", syncFullscreenState);
  }, []);

  useEffect(() => {
    if (fullscreenMode !== "fallback") return;
    function exitFallback(event: KeyboardEvent) {
      if (event.key === "Escape") setFullscreenMode("none");
    }
    document.addEventListener("keydown", exitFallback);
    return () => document.removeEventListener("keydown", exitFallback);
  }, [fullscreenMode]);

  async function toggleFullscreen() {
    const panel = panelRef.current;
    if (!panel) return;

    if (fullscreenMode === "native" && document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    if (fullscreenMode === "fallback") {
      setFullscreenMode("none");
      return;
    }

    if (panel.requestFullscreen) {
      try {
        await panel.requestFullscreen();
        setFullscreenMode("native");
        return;
      } catch {
        // Browsers may reject fullscreen in embeds; retain a local accessible fallback.
      }
    }
    setFullscreenMode("fallback");
  }

  return (
    <section
      ref={panelRef}
      className={clsx(
        "workspace-panel source-panel",
        fullscreenMode === "fallback" && "source-panel-fullscreen",
      )}
      aria-label="Source document"
    >
      <header className="workspace-panel-header">
        <div>
          <strong>Original</strong>
          <span>Page {page.page_number} · bbox1000</span>
        </div>
        <div
          className="viewer-tools"
          role="toolbar"
          aria-label="Source viewer tools"
        >
          <button
            className="tool-button"
            type="button"
            onClick={() => setOverlayVisible((visible) => !visible)}
            aria-pressed={overlayVisible}
          >
            {overlayVisible ? (
              <Eye size={15} aria-hidden="true" />
            ) : (
              <EyeSlash size={15} aria-hidden="true" />
            )}
            Overlay
          </button>
          <button
            className="tool-button"
            type="button"
            onClick={() => setRawTextVisible((visible) => !visible)}
            aria-pressed={rawTextVisible}
            aria-label="Source text layer"
          >
            <FileText size={15} aria-hidden="true" />
            Raw text
          </button>
          <span className="tool-separator" />
          <button
            className="icon-button compact"
            type="button"
            aria-label="Zoom out"
            onClick={() => setZoom((value) => Math.max(60, value - 10))}
          >
            <MagnifyingGlassMinus size={16} aria-hidden="true" />
          </button>
          <output aria-live="polite">{zoom}%</output>
          <button
            className="icon-button compact"
            type="button"
            aria-label="Zoom in"
            onClick={() => setZoom((value) => Math.min(180, value + 10))}
          >
            <MagnifyingGlassPlus size={16} aria-hidden="true" />
          </button>
          <button
            className="icon-button compact"
            type="button"
            aria-label={`Rotate page, currently ${rotation} degrees`}
            onClick={() => setRotation((value) => (value + 90) % 360)}
          >
            <ArrowClockwise size={16} aria-hidden="true" />
          </button>
          <button
            className="icon-button compact"
            type="button"
            aria-label={fullscreen ? "Exit full screen" : "Full screen"}
            aria-pressed={fullscreen}
            onClick={() => void toggleFullscreen()}
          >
            {fullscreen ? (
              <ArrowsIn size={16} aria-hidden="true" />
            ) : (
              <ArrowsOut size={16} aria-hidden="true" />
            )}
          </button>
        </div>
      </header>
      <div className="source-canvas">
        <div
          className="paper-wrap"
          style={{
            transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
          }}
          aria-label={`Source page ${page.page_number}`}
        >
          {sample ? (
            <SamplePaper pageNumber={page.page_number} />
          ) : (
            <div className="paper-page real-source-page">
              {page.thumbnail_url ? (
                // The URL is a short-lived, authenticated page preview supplied by the API.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  className="source-preview-image"
                  src={apiAbsoluteUrl(page.thumbnail_url)}
                  alt={`Preview of source page ${page.page_number}`}
                />
              ) : (
                <div className="honest-state compact">
                  <p>
                    A safe preview has not been generated for this page yet.
                  </p>
                </div>
              )}
              <span className="paper-page-number">{page.page_number}</span>
            </div>
          )}
          {overlayVisible && (
            <div className="bbox-layer" aria-label="Detected document blocks">
              {blocks.flatMap((block) =>
                block.source_refs.flatMap((source, sourceIndex) => {
                  const bbox = source.bbox1000;
                  if (!bbox || source.page_number !== page.page_number) {
                    return [];
                  }
                  const highlighted =
                    highlightedEvidence?.blockId === block.id &&
                    sameSource(highlightedEvidence.source, source);
                  const active = block.id === selectedBlockId || highlighted;
                  return [
                    <button
                      key={`${block.id}:${sourceIndex}:${bbox.join(",")}`}
                      type="button"
                      className={clsx(
                        "bbox-rect",
                        `bbox-${block.type}`,
                        active && "active",
                        highlighted && "highlighted",
                      )}
                      style={bboxStyle(bbox)}
                      onMouseEnter={() =>
                        onEvidenceInteraction?.(block.id, source, "focus")
                      }
                      onMouseLeave={() =>
                        onEvidenceInteraction?.(block.id, source, "blur")
                      }
                      onFocus={() =>
                        onEvidenceInteraction?.(block.id, source, "focus")
                      }
                      onBlur={() =>
                        onEvidenceInteraction?.(block.id, source, "blur")
                      }
                      onClick={() => {
                        onSelectBlock(block.id);
                        onEvidenceInteraction?.(block.id, source, "select");
                      }}
                      aria-label={`${block.type} block ${block.order}, evidence ${
                        sourceIndex + 1
                      } on page ${source.page_number}`}
                    >
                      <span>{block.type}</span>
                    </button>,
                  ];
                }),
              )}
            </div>
          )}
          {rawTextVisible && (
            <div
              className="source-text-layer"
              aria-label="Extracted source text"
            >
              {rawBlocks.length > 0 ? (
                rawBlocks.map((block) => (
                  <button
                    key={block.id}
                    type="button"
                    className={clsx(
                      "source-text-block",
                      block.id === selectedBlockId && "active",
                    )}
                    style={bboxStyle(block.source_refs[0]!.bbox1000!)}
                    onClick={() => onSelectBlock(block.id)}
                    aria-label={`${block.type} source block ${block.order}: ${block.source_text}`}
                  >
                    {block.source_text}
                  </button>
                ))
              ) : (
                <p className="source-text-empty">
                  There is no source text to display on this page.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
      <footer className="source-footer">
        <span>
          <i className="legend-dot native" /> Native extracted
        </span>
        <span>
          <i className="legend-dot ocr" /> OCR extracted
        </span>
        <span>
          <i className="legend-dot warning" /> Review
        </span>
      </footer>
    </section>
  );
}

function SamplePaper({ pageNumber }: { pageNumber: number }) {
  return (
    <article className="paper-page">
      <div className="paper-journal">
        SAMPLE · JOURNAL OF RELIABLE AI SYSTEMS
      </div>
      <h2>Evaluating evidence fidelity in retrieval-augmented generation</h2>
      <p className="paper-authors">Demo document · not an actual source</p>
      <hr />
      <h3>4.2 Experimental results</h3>
      <p>
        This content is a UI validation sample. Production mode displays only
        the API-issued source preview and stored bounding boxes.
      </p>
      <table>
        <caption>Table 3. Sample comparison</caption>
        <thead>
          <tr>
            <th>Configuration</th>
            <th>Evidence fidelity</th>
            <th>Unsupported claim</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Baseline</td>
            <td>0.86</td>
            <td>3.8%</td>
          </tr>
          <tr>
            <td>Verification enabled</td>
            <td>0.94</td>
            <td>1.1%</td>
          </tr>
        </tbody>
      </table>
      <span className="paper-page-number">{pageNumber}</span>
    </article>
  );
}

function sameSource(left: SourceRef, right: SourceRef): boolean {
  return (
    left.document_version_id === right.document_version_id &&
    left.page_number === right.page_number &&
    (left.bbox1000?.join(",") ?? "") === (right.bbox1000?.join(",") ?? "")
  );
}

function fallbackBlocks(pageNumber: number): CanonicalBlock[] {
  const base = {
    content_layer: "structured" as const,
    origin: "native_extracted" as const,
    quality_flags: [],
    revision: 1,
  };
  const ref = (bbox1000: [number, number, number, number]) => [
    {
      document_id: "doc_demo",
      document_version_id: "dver_demo",
      page_index: pageNumber - 1,
      page_number: pageNumber,
      bbox1000,
    },
  ];
  return [
    {
      ...base,
      id: `fallback-title-${pageNumber}`,
      order: 1,
      type: "title",
      markdown: "",
      source_text:
        "Evaluating evidence fidelity in retrieval-augmented generation",
      source_refs: ref([112, 94, 882, 158]),
    },
    {
      ...base,
      id: `fallback-heading-${pageNumber}`,
      order: 2,
      type: "heading",
      markdown: "",
      source_text: "4.2 Experimental results",
      source_refs: ref([106, 194, 452, 240]),
    },
    {
      ...base,
      id: `fallback-copy-${pageNumber}`,
      order: 3,
      type: "paragraph",
      markdown: "",
      source_text:
        "This content is a UI validation sample. Production mode displays source text.",
      source_refs: ref([108, 258, 892, 364]),
    },
    {
      ...base,
      id: `fallback-table-${pageNumber}`,
      order: 4,
      type: "table",
      markdown: "",
      source_text:
        "Configuration Evidence fidelity Unsupported claim Baseline 0.86 3.8% Verification enabled 0.94 1.1%",
      source_refs: ref([112, 402, 888, 644]),
    },
  ];
}
