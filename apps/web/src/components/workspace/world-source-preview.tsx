"use client";

import { Warning } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { apiRequest } from "@/lib/api-client";

type Capability = {
  read_url: string;
  expires_in_seconds: number;
  content_type: "application/pdf";
};

export function WorldSourcePreview({
  documentVersionId,
  pageNumber,
  bbox1000,
  label,
}: {
  documentVersionId: string;
  pageNumber: number;
  bbox1000: number[];
  label: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    let cancelRender: (() => void) | undefined;
    let destroyDocument: (() => Promise<void>) | undefined;
    void (async () => {
      setState("loading");
      try {
        const capability = await apiRequest<Capability>(
          `/v1/document-versions/${documentVersionId}/source-capability`,
        );
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/proof-sources/pdf.worker-6.2.108.min.mjs";
        const loadingTask = pdfjs.getDocument({ url: capability.read_url });
        destroyDocument = async () => {
          await loadingTask.destroy();
        };
        const document = await loadingTask.promise;
        const page = await document.getPage(pageNumber);
        const base = page.getViewport({ scale: 1 });
        const width = Math.max(260, hostRef.current?.clientWidth ?? 520);
        const viewport = page.getViewport({ scale: Math.min(1.5, width / base.width) });
        const canvas = canvasRef.current;
        const context = canvas?.getContext("2d");
        if (!canvas || !context || cancelled) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        const task = page.render({ canvas, canvasContext: context, viewport });
        cancelRender = () => task.cancel();
        await task.promise;
        if (!cancelled) setState("ready");
      } catch {
        if (!cancelled) setState("unavailable");
      }
    })();
    return () => {
      cancelled = true;
      cancelRender?.();
      void destroyDocument?.();
    };
  }, [documentVersionId, pageNumber]);

  const validBbox = bbox1000.length === 4 && bbox1000.every(Number.isFinite);
  return (
    <div ref={hostRef} className="world-source-preview" data-state={state}>
      {state === "loading" && <p>Opening the authorized source page…</p>}
      {state === "unavailable" && (
        <p role="status"><Warning size={15} /> Source capability is unavailable. No placeholder page is shown.</p>
      )}
      <div className="world-source-canvas">
        <canvas ref={canvasRef} aria-label={`${label}, page ${pageNumber}`} />
        {state === "ready" && validBbox && (
          <i style={{
            left: `${bbox1000[0]! / 10}%`,
            top: `${bbox1000[1]! / 10}%`,
            width: `${(bbox1000[2]! - bbox1000[0]!) / 10}%`,
            height: `${(bbox1000[3]! - bbox1000[1]!) / 10}%`,
          }} aria-hidden="true" />
        )}
      </div>
      <small>Actual sanitized PDF · PDF.js · p.{pageNumber} · bbox [{bbox1000.join(", ")}]</small>
    </div>
  );
}
