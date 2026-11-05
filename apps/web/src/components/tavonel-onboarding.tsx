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

const COPY = {
  en: {
    project: "First knowledge project",
    steps: ["Goal", "Document type", "Privacy", "First upload"],
    headings: [
      "What do you want to build?",
      "What will you compile first?",
      "Choose the processing boundary.",
      "Start with your first source.",
    ],
    descriptions: [
      "This choice sets helpful defaults. It never locks your project to a model or output.",
      "Choose the dominant source type. Mixed collections remain supported.",
      "External processing stays disabled unless the selected policy and a later approval allow it.",
      "Start with local selection, a public sample, or the deterministic demo.",
    ],
    choices: [
      [
        "Clean Markdown",
        "Obsidian Vault",
        "AI / RAG knowledge",
        "Ontology / Graph",
        "Not sure yet",
      ],
      [
        "Reports",
        "Research papers",
        "Course materials",
        "Manuals",
        "Contracts",
        "Mixed files",
      ],
      [
        "Ask before external processing",
        "Never use external processing",
        "Allow approved providers",
      ],
      ["Choose files", "Use the public sample", "Explore the demo first"],
    ],
    progress: "Onboarding progress",
    back: "Back",
    continue: "Continue",
    openUpload: "Open upload",
  },
  ko: {
    project: "첫 지식 프로젝트",
    steps: ["목표", "문서 유형", "개인정보", "첫 업로드"],
    headings: [
      "무엇을 만들고 싶나요?",
      "어떤 문서를 먼저 컴파일할까요?",
      "처리 경계를 선택하세요.",
      "첫 원문으로 시작하세요.",
    ],
    descriptions: [
      "이 선택은 유용한 기본값만 정하며 특정 모델이나 출력 형식에 프로젝트를 고정하지 않습니다.",
      "주요 원문 유형을 선택하세요. 여러 형식이 섞인 컬렉션도 지원합니다.",
      "선택한 정책과 이후 승인이 모두 허용하기 전에는 외부 처리를 사용하지 않습니다.",
      "로컬 파일, 공개 샘플 또는 결정론적 데모로 시작할 수 있습니다.",
    ],
    choices: [
      [
        "정돈된 Markdown",
        "Obsidian Vault",
        "AI / RAG 지식",
        "온톨로지 / 그래프",
        "아직 모르겠음",
      ],
      ["보고서", "연구 논문", "강의 자료", "매뉴얼", "계약서", "혼합 파일"],
      ["외부 처리 전 확인", "외부 처리 사용 안 함", "승인된 제공자 허용"],
      ["파일 선택", "공개 샘플 사용", "데모 먼저 살펴보기"],
    ],
    progress: "온보딩 진행",
    back: "이전",
    continue: "계속",
    openUpload: "컬렉션 수집 열기",
  },
} as const;

export function TavonelOnboarding() {
  const { locale } = useStructaraLocale();
  const copy = COPY[locale];
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Record<number, string>>({});
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
        <div className="tv-onboarding-progress" aria-label={copy.progress}>
          {copy.steps.map((label, index) => (
            <span key={label} data-active={index <= step}>
              <i>{index < step ? <Check size={12} /> : index + 1}</i>
              {label}
            </span>
          ))}
        </div>
        <div className="tv-onboarding-copy">
          <p>{copy.steps[step]}</p>
          <h1>{copy.headings[step]}</h1>
          <span>{copy.descriptions[step]}</span>
        </div>
        <div className="tv-onboarding-options">
          {choices.map((choice) => (
            <button
              type="button"
              key={choice}
              data-selected={selected[step] === choice}
              onClick={() =>
                setSelected((value) => ({ ...value, [step]: choice }))
              }
            >
              {step === copy.steps.length - 1 && <FileArrowUp size={17} />}
              <span>{choice}</span>
              {selected[step] === choice && <Check size={15} />}
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
              disabled={!selected[step]}
              onClick={() => setStep((value) => value + 1)}
            >
              {copy.continue} <ArrowRight size={14} />
            </button>
          ) : (
            <Link className="tv-app-primary" href="/quick-convert">
              {copy.openUpload} <ArrowRight size={14} />
            </Link>
          )}
        </footer>
      </section>
    </main>
  );
}
