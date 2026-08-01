"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import {
  Component,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { StructaraLocale } from "@/lib/locale";

const WebglScene = dynamic(() => import("./structara-webgl-scene"), {
  ssr: false,
  loading: () => null,
});

class WebglFallbackBoundary extends Component<
  { children: ReactNode; onFailure: () => void },
  { failed: boolean }
> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override componentDidCatch() {
    this.props.onFailure();
  }

  override render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function hasUsableWebGL2(
  canvas: HTMLCanvasElement = document.createElement("canvas"),
) {
  try {
    const context = canvas.getContext("webgl2", {
      failIfMajorPerformanceCaveat: true,
    });
    if (!context) return false;
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export function StructaraHeroScene({ locale }: { locale: StructaraLocale }) {
  const [enhance, setEnhance] = useState(false);
  const [settled, setSettled] = useState(false);
  const [sceneRun, setSceneRun] = useState(0);
  const [inView, setInView] = useState(true);
  const [documentVisible, setDocumentVisible] = useState(true);
  const sceneRef = useRef<HTMLDivElement>(null);
  const settleScene = useCallback(() => setSettled(true), []);
  const disableScene = useCallback(() => setEnhance(false), []);

  useEffect(() => {
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const narrow = window.matchMedia("(max-width: 960px)").matches;
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (reduced || narrow || connection?.saveData || !hasUsableWebGL2()) return;

    const id = window.requestIdleCallback(() => setEnhance(true), {
      timeout: 1600,
    });
    return () => {
      window.cancelIdleCallback(id);
    };
  }, []);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(Boolean(entry?.isIntersecting)),
      { rootMargin: "120px" },
    );
    const handleVisibility = () => setDocumentVisible(!document.hidden);
    observer.observe(scene);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  return (
    <div
      ref={sceneRef}
      className="st-hero-scene"
      data-enhanced={enhance}
      data-settled={settled}
      data-truth-class="first-party-illustrative-3d"
    >
      <picture className="st-hero-render">
        <source
          media="(max-width: 640px)"
          srcSet="/hero/STR-HOME-T2-HERO-EN-MOBILE-1080x1440-v01.avif"
          type="image/avif"
        />
        <source
          media="(max-width: 960px)"
          srcSet="/hero/STR-HOME-T2-HERO-EN-TABLET-1600x1200-v01.avif"
          type="image/avif"
        />
        <source
          srcSet="/hero/STR-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.avif"
          type="image/avif"
        />
        <Image
          src="/hero/STR-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.webp"
          alt=""
          width={2880}
          height={1800}
          decoding="async"
          loading="lazy"
          fetchPriority="low"
          sizes="(max-width: 640px) 100vw, (max-width: 960px) 92vw, 50vw"
        />
      </picture>
      {enhance && (
        <div className="st-webgl-layer" aria-hidden="true">
          <WebglFallbackBoundary key={sceneRun} onFailure={disableScene}>
            <WebglScene
              active={inView && documentVisible && !settled}
              onSettled={settleScene}
              onContextFailure={disableScene}
            />
          </WebglFallbackBoundary>
        </div>
      )}
      <p className="sr-only">
        {locale === "ko"
          ? "서로 다른 보고서, 논문, 표와 매뉴얼이 의미 블록으로 분해되고 검증된 뒤 하나의 지식 구조로 결합되는 애니메이션."
          : "Reports, papers, tables, and manuals separate into semantic blocks, receive source verification, and compile into one knowledge plane."}
      </p>
      <div className="st-hero-scene-meta">
        <small>12 SOURCES → VERIFIED KNOWLEDGE PLANE</small>
        {enhance && settled && (
          <button
            type="button"
            onClick={() => {
              setSettled(false);
              setSceneRun((value) => value + 1);
            }}
          >
            {locale === "ko" ? "장면 다시 보기" : "Replay scene"}
          </button>
        )}
      </div>
    </div>
  );
}
