"use client";

import { Pause, Play } from "@phosphor-icons/react";
import { useRef, useState } from "react";

import { publicBenchmarkSnapshot } from "@/lib/benchmark-public";
import type { StructaraLocale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "Evidence in Motion · 60 seconds",
    title: "Watch documents become a verified knowledge system.",
    body: "A condensed product film using the measured parser portfolio and its signed evaluation release. Product timing is condensed; benchmark values are not.",
    play: "Play evidence film",
    pause: "Pause evidence film",
  },
  ko: {
    eyebrow: "움직이는 근거 · 60초",
    title: "문서가 검증된 지식 시스템이 되는 과정을 보세요.",
    body: "실측한 파서 포트폴리오와 서명된 평가 릴리스를 제품 흐름에 연결한 영상입니다. 제품 장면의 시간은 압축했지만 벤치마크 수치는 압축하지 않았습니다.",
    play: "근거 영상 재생",
    pause: "근거 영상 일시정지",
  },
} as const;

export function EvidenceFilm({ locale }: { locale: StructaraLocale }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const strings = copy[locale];
  const candidateCount = publicBenchmarkSnapshot.datasets.filter(
    (dataset) => dataset.status === "available",
  ).length;
  const disclosure =
    locale === "ko"
      ? `OmniDocBench 공식 데모 · 18페이지 · 3회 반복 · ${candidateCount}개 후보 · RTX 4090`
      : `OmniDocBench official demo · 18 pages · 3 repeats · ${candidateCount} candidates · RTX 4090`;

  async function toggle() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) await video.play();
    else video.pause();
  }

  return (
    <section className="st-evidence-film" aria-labelledby="evidence-film-title">
      <div className="st-evidence-film-copy">
        <p>{strings.eyebrow}</p>
        <h2 id="evidence-film-title">{strings.title}</h2>
        <span>{strings.body}</span>
        <small>{disclosure}</small>
      </div>
      <div className="st-evidence-film-frame">
        <video
          ref={videoRef}
          poster="/film/structara-evidence-in-motion-poster.webp"
          preload="metadata"
          playsInline
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
        >
          <source src="/film/structara-evidence-in-motion-60s.webm" type="video/webm" />
          <source src="/film/structara-evidence-in-motion-60s.mp4" type="video/mp4" />
          <track kind="captions" src="/film/structara-evidence-in-motion.en.vtt" srcLang="en" label="English" default />
        </video>
        <button type="button" onClick={() => void toggle()} aria-label={playing ? strings.pause : strings.play}>
          {playing ? <Pause weight="fill" aria-hidden="true" /> : <Play weight="fill" aria-hidden="true" />}
          <span>{playing ? strings.pause : strings.play}</span>
        </button>
      </div>
    </section>
  );
}
