"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import type { StructaraLocale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "Actual product film",
    title: "Watch measured evidence move through the product.",
    body: "A 60-second composite joins deterministic product scenes to 270 measured model-inference cases. Product sequences are condensed; benchmark values are measured and hashed.",
    open: "Play the 60-second film",
    close: "Close film",
    dialog: "Evidence in Motion product film",
    transcript: "Transcript",
    transcriptBody:
      "Sources enter a controlled collection, receive an adaptive route, become page blocks, return to source evidence, compile into knowledge relations, and leave as portable packages. The film then presents the five measured parser candidates and their evidence bundle.",
  },
  ko: {
    eyebrow: "실제 제품 필름",
    title: "실측 근거가 제품을 통과하는 과정을 확인하세요.",
    body: "60초 합성 필름이 결정론적 제품 장면과 모델 정식 추론 270건을 연결합니다. 제품 장면은 시간을 압축했고, 벤치마크 수치는 실제 측정값과 해시를 사용합니다.",
    open: "60초 필름 재생",
    close: "필름 닫기",
    dialog: "Evidence in Motion 제품 필름",
    transcript: "대본",
    transcriptBody:
      "원본이 통제된 컬렉션에 들어와 적응형 경로를 받고, 페이지 블록과 원본 근거로 연결된 뒤 지식 관계와 이식 가능한 패키지로 컴파일됩니다. 이어서 실측한 다섯 파서 후보와 증거 번들을 보여줍니다.",
  },
} as const;

export function ProductFilmDialog({ locale }: { locale: StructaraLocale }) {
  const text = copy[locale];
  const dialogRef = useRef<HTMLDialogElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <section
      className="st-product-film-dialog"
      data-truth-class="measured-product-composite"
      data-evidence="benchmark-evidence-bundle"
    >
      <div>
        <p>{text.eyebrow}</p>
        <h2>{text.title}</h2>
        <span>{text.body}</span>
        <button type="button" onClick={() => setOpen(true)}>
          <i aria-hidden="true">▶</i>
          {text.open}
        </button>
      </div>
      <button
        type="button"
        className="st-film-thumbnail"
        aria-label={`Open Evidence in Motion film preview — 60 SEC · 270 FORMAL CASES · 5 CANDIDATES`}
        onClick={() => setOpen(true)}
      >
        <Image
          src="/film/structara-evidence-in-motion-poster.webp"
          alt=""
          width={1440}
          height={900}
          sizes="(max-width: 768px) 100vw, 56vw"
        />
        <span>Evidence in Motion</span>
        <small>60 SEC · 270 FORMAL CASES · 5 CANDIDATES</small>
      </button>
      <dialog
        ref={dialogRef}
        className="st-film-modal"
        aria-label={text.dialog}
        onClose={() => {
          videoRef.current?.pause();
          setOpen(false);
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) event.currentTarget.close();
        }}
      >
        <div>
          <header>
            <strong>Evidence in Motion</strong>
            <button type="button" onClick={() => dialogRef.current?.close()}>
              {text.close}
            </button>
          </header>
          <video
            ref={videoRef}
            controls
            preload="none"
            poster="/film/structara-evidence-in-motion-poster.webp"
          >
            <source
              src="/film/structara-evidence-in-motion-60s.webm"
              type="video/webm"
            />
            <source
              src="/film/structara-evidence-in-motion-60s.mp4"
              type="video/mp4"
            />
            <track
              kind="captions"
              src="/film/structara-evidence-in-motion.en.vtt"
              srcLang="en"
              label="English"
              default
            />
          </video>
          <details>
            <summary>{text.transcript}</summary>
            <p>{text.transcriptBody}</p>
          </details>
        </div>
      </dialog>
    </section>
  );
}
