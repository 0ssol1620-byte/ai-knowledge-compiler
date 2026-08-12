"use client";

import { useEffect, useRef, useState } from "react";

import { TavonelGlyph } from "@/components/tavonel-glyph";
import type { StructaraLocale } from "@/lib/locale";

type Chapter = {
  id: string;
  number: string;
  title: string;
  body: string;
  signal: string;
};

const labels = {
  en: {
    eyebrow: "04 · Compiler transformation",
    title: "Understand. Verify. Connect. Activate.",
    visual: "Active transformation",
    source: "Source page",
    result: "Verified output",
  },
  ko: {
    eyebrow: "04 · 컴파일러 변환",
    title: "이해하고, 검증하고, 연결하고, 활성화합니다.",
    visual: "현재 변환 단계",
    source: "원본 페이지",
    result: "검증된 출력",
  },
} as const;

export function TransformationStory({
  locale,
  chapters,
}: {
  locale: StructaraLocale;
  chapters: readonly Chapter[];
}) {
  const [active, setActive] = useState(0);
  const itemsRef = useRef<Array<HTMLElement | null>>([]);
  const text = labels[locale];

  useEffect(() => {
    const items = itemsRef.current.filter(Boolean) as HTMLElement[];
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        const index = Number((visible.target as HTMLElement).dataset.index);
        if (Number.isFinite(index)) setActive(index);
      },
      { rootMargin: "-28% 0px -42%", threshold: [0.25, 0.55, 0.8] },
    );
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, []);

  const chapter = chapters[active] ?? chapters[0];
  if (!chapter) return null;

  return (
    <section
      id="transformation"
      className="st-reference-story folynta-scene"
      data-scene="04-transformation"
      data-signature-asset="A06"
      data-signature-assets="A02 A03 A04"
      data-truth-class="deterministic-reference-scene"
    >
      <header>
        <p>{text.eyebrow}</p>
        <h2>{text.title}</h2>
      </header>
      <div className="st-story-grid">
        <div className="st-story-copy">
          {chapters.map((item, index) => (
            <article
              key={item.id}
              id={`transformation-${item.id}`}
              data-index={index}
              data-active={index === active}
              ref={(node) => {
                itemsRef.current[index] = node;
              }}
              tabIndex={0}
              onFocus={() => setActive(index)}
            >
              <span>{item.number}</span>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
              <small>{item.signal}</small>
            </article>
          ))}
        </div>
        <aside className="st-story-visual" aria-label={text.visual}>
          <div className="st-story-status">
            <span>{chapter.number}</span>
            <strong>{chapter.title}</strong>
          </div>
          <div className={`st-story-scene st-story-scene-${active + 1}`}>
            <div>
              <small>{text.source}</small>
              <i />
              <i />
              <b />
            </div>
            <span className="st-story-evidence" />
            <div>
              <TavonelGlyph
                name={
                  active === 0
                    ? "block"
                    : active === 1
                      ? "evidence"
                      : active === 2
                        ? "node"
                        : "package"
                }
                size={30}
              />
              <small>{text.result}</small>
              <strong>{chapter.signal}</strong>
            </div>
          </div>
          <nav aria-label={text.eyebrow}>
            {chapters.map((item, index) => (
              <a
                key={item.id}
                href={`#transformation-${item.id}`}
                aria-current={index === active ? "step" : undefined}
                onClick={() => setActive(index)}
              >
                {item.number}
              </a>
            ))}
          </nav>
        </aside>
      </div>
    </section>
  );
}
