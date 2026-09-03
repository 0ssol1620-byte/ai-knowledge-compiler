"use client";

import { useRef, useState } from "react";

import { useStructaraLocale } from "@/components/locale-provider";

/**
 * A recording of the ingest path actually running.
 *
 * Recorded rather than animated, and the distinction is the whole point. §10.4
 * forbids typing simulation, and a fabricated progress sequence is the same
 * thing wearing a different costume: it shows a process that did not happen.
 * This is a Playwright capture of the real drop zone talking to the real API —
 * the four calls below returned the statuses shown, and the page count is what
 * the parser actually counted.
 *
 *   201  POST /v1/trial/sessions
 *   201  POST /v1/trial/sessions/{id}/uploads
 *   204  PUT  .../content
 *   200  POST .../complete          ->  "Preflight read all 3 pages"
 *
 * WHAT IT DOES NOT SHOW, said here because the caption says it on screen. The
 * trial path runs UPLOADED -> SECURITY_SCANNING -> SECURITY_VERIFIED ->
 * PREFLIGHTING -> PREFLIGHTED. That is five of the eight stages. Extraction,
 * knowledge construction and packaging run on GPU workers, and ADR-006 keeps
 * them behind a principal, so they were not part of this run and are not
 * implied by it.
 *
 * No autoplay. §10.4 rules out motion that starts on its own, and Vercel's own
 * guidance — quoted in §9.2 when the 3D scene was dropped — is to animate in
 * response to user actions. The poster is the final frame, so the still frame
 * already carries the result and pressing play is optional rather than
 * necessary.
 */
export function TrialRunFilm() {
  const { locale } = useStructaraLocale();
  const korean = locale === "ko";
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  return (
    <section className="tv-film" id="watch">
      <div className="tv-film-copy">
        <p className="tv-film-eyebrow">{korean ? "애니메이션이 아닌 실제 기록" : "Recorded, not animated"}</p>
        <h2>{korean ? "공시 문서가 처리 게이트를 통과하는 과정을 확인하세요." : "Watch a filing go through the gate."}</h2>
        <p className="tv-film-lead">
          {korean
            ? "위 화면에 3페이지 공개 공시를 넣었습니다. 문서를 읽기 전에 보안 검사와 사전 분석이 실행되며, 마지막 페이지 수는 파서가 실제로 센 결과입니다."
            : "A three-page public filing dropped on the page above. Security scanning and preflight run before anything reads the document, and the page count at the end is what the parser counted."}
        </p>
      </div>

      <figure className="tv-film-frame">
        <video
          ref={video}
          className="tv-film-video"
          poster="/media/trial-run-poster.avif"
          width={1120}
          height={560}
          playsInline
          preload="none"
          controls={playing}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        >
          <source src="/media/trial-run.webm" type="video/webm" />
          <source src="/media/trial-run.mp4" type="video/mp4" />
        </video>

        {!playing && (
          // A real button over the poster rather than a click handler on the
          // video: §21 asks for platform controls, and this one is reachable by
          // keyboard because it is a button.
          <button
            type="button"
            className="tv-film-play"
            onClick={() => void video.current?.play()}
          >
            <span aria-hidden="true">▶</span>
            {korean ? "실행 재생 · 13초 · 무음" : "Play the run · 13 seconds, no sound"}
          </button>
        )}

        <figcaption className="tv-film-caption">
          {korean
            ? "실제 수집 API 실행 기록입니다. 8개 파이프라인 단계 중 업로드, 보안 검사, 사전 분석까지 5개 단계를 다룹니다. 추출, 지식 구성, 패키징은 계정 뒤의 워커에서 실행되므로 여기에는 표시하지 않습니다."
            : "Real run against the live ingest API. It covers upload, security scanning and preflight — five of the eight pipeline stages. Extraction, knowledge construction and packaging run on workers behind an account and are not shown here."}
        </figcaption>
      </figure>
    </section>
  );
}
