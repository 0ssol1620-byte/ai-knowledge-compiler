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

const ONBOARDING = {
  en: {
    project: "First knowledge project",
    progress: "Onboarding progress",
    steps: ["Goal", "Document type", "Privacy", "First upload"],
    questions: [
      "What do you want to build?",
      "What will you compile first?",
      "Choose the processing boundary.",
      "Start with your first source.",
    ],
    note: "This choice sets helpful defaults. It never locks your project to a model or output.",
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
    back: "Back",
    continue: "Continue",
    openUpload: "Open collection intake",
  },
  ko: {
    project: "첫 번째 지식 프로젝트",
    progress: "온보딩 진행 상태",
    steps: ["목표", "문서 유형", "개인정보", "첫 업로드"],
    questions: [
      "무엇을 만들고 싶나요?",
      "어떤 문서를 먼저 컴파일할까요?",
      "처리 경계를 선택하세요.",
      "첫 번째 원본으로 시작하세요.",
    ],
    note: "이 선택은 도움이 되는 기본값을 설정하지만 프로젝트를 특정 모델이나 출력에 종속시키지 않습니다.",
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
    back: "이전",
    continue: "계속",
    openUpload: "컬렉션 수집 열기",
  },
} as const;

export function StructaraOnboarding() {
  const { locale } = useStructaraLocale();
  const copy = ONBOARDING[locale];
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const currentLabel = copy.steps[step]!;
  const currentChoices = copy.choices[step]!;

  return (
    <main id="main-content" className="st-onboarding" data-locale={locale}>
      <header>
        <Link href="/">FOLYNTA</Link>
        <span>{copy.project}</span>
        <small>
          {step + 1} / {copy.steps.length}
        </small>
      </header>
      <section>
        <div className="st-onboarding-progress" aria-label={copy.progress}>
          {copy.steps.map((label, index) => (
            <span key={label} data-active={index <= step}>
              <i>{index < step ? <Check size={12} /> : index + 1}</i>
              {label}
            </span>
          ))}
        </div>
        <div className="st-onboarding-copy">
          <p>{currentLabel}</p>
          <h1>{copy.questions[step]}</h1>
          <span>{copy.note}</span>
        </div>
        <div className="st-onboarding-options">
          {currentChoices.map((choice) => (
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
              className="st-app-primary"
              disabled={!selected[step]}
              onClick={() => setStep((value) => value + 1)}
            >
              {copy.continue} <ArrowRight size={14} />
            </button>
          ) : (
            <Link className="st-app-primary" href="/intake">
              {copy.openUpload} <ArrowRight size={14} />
            </Link>
          )}
        </footer>
      </section>
    </main>
  );
}
