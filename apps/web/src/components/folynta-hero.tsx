"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

const WebglScene = dynamic(() => import("./folynta-webgl-scene"), {
  ssr: false,
  loading: () => null,
});

export function FolyntaHeroScene() {
  const [enhance, setEnhance] = useState(false);
  const [inView, setInView] = useState(true);
  const [documentVisible, setDocumentVisible] = useState(true);
  const sceneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const narrow = window.matchMedia("(max-width: 960px)").matches;
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (reduced || narrow || connection?.saveData) return;

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
    <div ref={sceneRef} className="fl-hero-scene" data-enhanced={enhance}>
      <picture className="fl-hero-render">
        <source
          media="(max-width: 640px)"
          srcSet="/hero/FLY-HOME-T2-HERO-EN-MOBILE-1080x1440-v01.avif"
          type="image/avif"
        />
        <source
          media="(max-width: 960px)"
          srcSet="/hero/FLY-HOME-T2-HERO-EN-TABLET-1600x1200-v01.avif"
          type="image/avif"
        />
        <source
          srcSet="/hero/FLY-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.avif"
          type="image/avif"
        />
        <Image
          src="/hero/FLY-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.webp"
          alt=""
          width={2880}
          height={1800}
          decoding="async"
          priority
          sizes="(max-width: 640px) 100vw, (max-width: 960px) 92vw, 50vw"
        />
      </picture>
      {enhance && (
        <div className="fl-webgl-layer" aria-hidden="true">
          <WebglScene active={inView && documentVisible} />
        </div>
      )}
      <small>First-party illustrative model · no generated imagery</small>
    </div>
  );
}
