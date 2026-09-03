"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileArrowUp,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";

import { useStructaraLocale } from "@/components/locale-provider";

const ONBOARDING_COPY = {
  en: {
    project: "First knowledge project",
    progress: "Onboarding progress",
    steps: ["Goal", "Document type", "Privacy", "First upload"],
    titles: [
      "What do you want to build?",
      "What will you compile first?",
      "Choose the processing boundary.",
      "Start with your first source.",
    ],
    description:
      "This choice sets helpful defaults. It never locks your project to a model or output.",
    choices: [
      ["Clean Markdown", "Obsidian Vault", "AI / RAG knowledge", "Ontology / Graph", "Not sure yet"],
      ["Reports", "Research papers", "Course materials", "Manuals", "Contracts", "Mixed files"],
      ["Ask before external processing", "Never use external processing", "Allow approved providers"],
      ["Choose files", "Use the public sample", "Explore the demo first"],
    ],
    back: "Back",
    continue: "Continue",
    open: "Open collection intake",
  },
  ko: {
    project: "첫 지식 프로젝트",
    progress: "온보딩 진행 상태",
    steps: ["목표", "문서 유형", "개인정보", "첫 업로드"],
    titles: [
      "무엇을 만들고 싶나요?",
      "먼저 무엇을 컴파일할까요?",
      "처리 범위를 선택하세요.",
      "첫 원본으로 시작하세요.",
    ],
    description:
      "이 선택은 유용한 기본값만 설정합니다. 프로젝트를 특정 모델이나 출력 형식에 고정하지 않습니다.",
    choices: [
      ["정돈된 Markdown", "Obsidian Vault", "AI / RAG 지식", "온톨로지 / 그래프", "아직 모르겠음"],
      ["보고서", "연구 논문", "강의 자료", "매뉴얼", "계약서", "혼합 파일"],
      ["외부 처리 전 확인", "외부 처리 사용 안 함", "승인된 제공자 허용"],
      ["파일 선택", "공개 샘플 사용", "데모 먼저 살펴보기"],
    ],
    back: "뒤로",
    continue: "계속",
    open: "컬렉션 수집 열기",
  },
} as const;

export function TavonelOnboarding() {
  const { locale } = useStructaraLocale();
  const copy = ONBOARDING_COPY[locale];
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const current = copy.steps[step]!;
  const choices = copy.choices[step]!;

  return (
    <main id="main-content" className="tv-onboarding">
      <header>
        <Link href="/">TAVONEL</Link>
        <span>{copy.project}</span>
        <small>
          {step + 1} / {copy.steps.length}
        </small>
      </header>
      <section>
        <div
          className="tv-onboarding-progress"
          aria-label={copy.progress}
        >
          {copy.steps.map((label, index) => (
            <span key={label} data-active={index <= step}>
              <i>{index < step ? <Check size={12} /> : index + 1}</i>
              {label}
            </span>
          ))}
        </div>
        <div className="tv-onboarding-copy">
          <p>{current}</p>
          <h1>{copy.titles[step]}</h1>
          <span>{copy.description}</span>
        </div>
        <div className="tv-onboarding-options">
          {choices.map((choice) => (
            <button
              type="button"
              key={choice}
              data-selected={selected[current] === choice}
              onClick={() =>
                setSelected((value) => ({ ...value, [current]: choice }))
              }
            >
              {step === copy.steps.length - 1 && <FileArrowUp size={17} />}
              <span>{choice}</span>
              {selected[current] === choice && <Check size={15} />}
            </button>
          ))}
        </div>
        <footer>
          <button
            type="button"
            disabled={step === 0}
            onClick={() => setStep((value) => value - 1)}
          >
            <ArrowLeft size={14} /> {copy.back}
          </button>
          {step < copy.steps.length - 1 ? (
            <button
              type="button"
              className="tv-app-primary"
              disabled={!selected[current]}
              onClick={() => setStep((value) => value + 1)}
            >
              {copy.continue} <ArrowRight size={14} />
            </button>
          ) : (
            <Link className="tv-app-primary" href="/quick-convert">
              {copy.open} <ArrowRight size={14} />
            </Link>
          )}
        </footer>
      </section>
    </main>
  );
}
