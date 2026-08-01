"use client";

import { useMemo, useState } from "react";

import { useStructaraLocale } from "@/components/locale-provider";

const plans = [
  {
    name: "Free",
    audience: "Individuals",
    summary: "Try core conversion with short retention.",
    includes: ["Limited pages", "Core conversion", "Short retention"],
  },
  {
    name: "Personal",
    audience: "Individuals",
    summary: "Clean Markdown and personal knowledge projects.",
    includes: ["Clean Markdown", "Basic Obsidian", "Personal projects"],
  },
  {
    name: "Pro",
    audience: "Individuals",
    summary: "Precision processing with proof and connected knowledge.",
    includes: ["Precision routes", "Source comparison", "Notes and graph"],
  },
  {
    name: "Team",
    audience: "Teams",
    summary: "Shared projects, reviewers, API, and audit basics.",
    includes: ["Shared projects", "Integrity roles", "API and audit"],
  },
  {
    name: "Business",
    audience: "Teams",
    summary: "Higher limits, retention controls, and organization roles.",
    includes: ["Retention controls", "Organization roles", "Priority support"],
  },
  {
    name: "Enterprise",
    audience: "Enterprise",
    summary: "Custom policy, region, deployment, identity, and SLA.",
    includes: ["Custom policy", "VPC or on-prem", "SSO and SCIM"],
  },
] as const;

type Audience = "Individuals" | "Teams" | "Enterprise";

const copy = {
  en: {
    eyebrow: "Plans and operating controls",
    title: "Choose the control surface, then size it.",
    audience: "Audience",
    audiences: {
      Individuals: "Individuals",
      Teams: "Teams",
      Enterprise: "Enterprise",
    },
    summaries: [
      "Try core conversion with short retention.",
      "Clean Markdown and personal knowledge projects.",
      "Precision processing with proof and connected knowledge.",
      "Shared projects, reviewers, API, and audit basics.",
      "Higher limits, retention controls, and organization roles.",
      "Custom policy, region, deployment, identity, and SLA.",
    ],
    includes: [
      ["Limited pages", "Core conversion", "Short retention"],
      ["Clean Markdown", "Basic Obsidian", "Personal projects"],
      ["Precision routes", "Source comparison", "Notes and graph"],
      ["Shared projects", "Integrity roles", "API and audit"],
      ["Retention controls", "Organization roles", "Priority support"],
      ["Custom policy", "VPC or on-prem", "SSO and SCIM"],
    ],
    estimateEyebrow: "Transparent estimate",
    estimateTitle: "Plan around the pages you actually process.",
    estimateBody:
      "This illustrative planning model exposes scan, Precision, and knowledge-output overhead. It is an estimate, not a quote.",
    monthlyPages: "Monthly pages",
    scanRatio: "Scan ratio",
    precisionRatio: "Precision ratio",
    knowledgeOutput: "Build knowledge notes and graph output",
    profile: "Estimated operating profile",
    recommended: "Recommended plan",
    creditRange: "Credit range",
    maximumDraw: "Maximum draw",
    credits: "credits",
    priceBook:
      "Monetary maximum, overage rate, storage extension, and annual discount appear only after the owner-approved price book is registered.",
  },
  ko: {
    eyebrow: "요금제와 운영 통제",
    title: "필요한 통제 수준을 선택한 뒤 처리량을 산정하세요.",
    audience: "사용 대상",
    audiences: {
      Individuals: "개인",
      Teams: "팀",
      Enterprise: "엔터프라이즈",
    },
    summaries: [
      "짧은 보존 기간으로 핵심 변환을 체험합니다.",
      "정돈된 Markdown과 개인 지식 프로젝트를 지원합니다.",
      "근거와 연결 지식을 포함한 정밀 처리를 지원합니다.",
      "공유 프로젝트, 검토자, API와 기본 감사를 제공합니다.",
      "더 높은 한도, 보존 통제와 조직 역할을 제공합니다.",
      "정책, 리전, 배포, ID와 SLA를 맞춤 구성합니다.",
    ],
    includes: [
      ["제한된 페이지", "핵심 변환", "짧은 보존"],
      ["정돈된 Markdown", "기본 Obsidian", "개인 프로젝트"],
      ["정밀 라우팅", "원본 비교", "노트와 그래프"],
      ["공유 프로젝트", "무결성 역할", "API와 감사"],
      ["보존 통제", "조직 역할", "우선 지원"],
      ["맞춤 정책", "VPC 또는 온프레미스", "SSO와 SCIM"],
    ],
    estimateEyebrow: "투명한 추정",
    estimateTitle: "실제로 처리할 페이지를 기준으로 계획하세요.",
    estimateBody:
      "이 예시용 계획 모델은 스캔, Precision, 지식 출력 오버헤드를 공개합니다. 견적이 아닌 추정치입니다.",
    monthlyPages: "월간 페이지",
    scanRatio: "스캔 비율",
    precisionRatio: "정밀 처리 비율",
    knowledgeOutput: "지식 노트와 그래프 출력 생성",
    profile: "예상 운영 프로필",
    recommended: "추천 요금제",
    creditRange: "크레딧 범위",
    maximumDraw: "최대 사용량",
    credits: "크레딧",
    priceBook:
      "금액 상한, 초과 요율, 스토리지 연장과 연간 할인은 소유자 승인을 받은 가격표가 등록된 뒤에만 표시됩니다.",
  },
} as const;

export function StructaraPricingPlanner() {
  const { locale } = useStructaraLocale();
  const text = copy[locale];
  const [audience, setAudience] = useState<Audience>("Individuals");
  const [pages, setPages] = useState(2500);
  const [scanRatio, setScanRatio] = useState(20);
  const [precisionRatio, setPrecisionRatio] = useState(15);
  const [knowledgeOutput, setKnowledgeOutput] = useState(true);

  const estimate = useMemo(() => {
    const weighted =
      pages *
      (1 +
        (scanRatio / 100) * 0.7 +
        (precisionRatio / 100) * 1.5 +
        (knowledgeOutput ? 0.15 : 0));
    const lower = Math.ceil((weighted * 0.9) / 100) * 100;
    const upper = Math.ceil((weighted * 1.15) / 100) * 100;
    const recommended =
      pages <= 100
        ? "Free"
        : pages <= 1000
          ? "Personal"
          : pages <= 5000
            ? "Pro"
            : pages <= 20000
              ? "Team"
              : pages <= 100000
                ? "Business"
                : "Enterprise";
    return { lower, upper, recommended };
  }, [knowledgeOutput, pages, precisionRatio, scanRatio]);

  return (
    <section
      className="st-pricing-system"
      aria-labelledby="pricing-plans-title"
      data-truth-class="illustrative-pricing-estimator"
    >
      <header>
        <p className="st-context-label">{text.eyebrow}</p>
        <h2 id="pricing-plans-title">{text.title}</h2>
        <div
          className="st-audience-switch"
          role="group"
          aria-label={text.audience}
        >
          {(["Individuals", "Teams", "Enterprise"] as const).map((item) => (
            <button
              type="button"
              key={item}
              aria-pressed={audience === item}
              onClick={() => setAudience(item)}
            >
              {text.audiences[item]}
            </button>
          ))}
        </div>
      </header>

      <div className="st-plan-ledger">
        {plans
          .filter((plan) => plan.audience === audience)
          .map((plan) => {
            const index = plans.indexOf(plan);
            const includes = text.includes[index] ?? plan.includes;
            return (
              <article key={plan.name}>
                <span>{text.audiences[plan.audience]}</span>
                <h3>{plan.name}</h3>
                <p>{text.summaries[index]}</p>
                <ul>
                  {includes.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </article>
            );
          })}
      </div>

      <div className="st-credit-planner">
        <div>
          <p className="st-context-label">{text.estimateEyebrow}</p>
          <h2>{text.estimateTitle}</h2>
          <p>{text.estimateBody}</p>
          <label>
            <span>
              {text.monthlyPages}{" "}
              <strong>{pages.toLocaleString(locale)}</strong>
            </span>
            <input
              type="range"
              min="100"
              max="150000"
              step="100"
              value={pages}
              onChange={(event) => setPages(Number(event.target.value))}
            />
          </label>
          <label>
            <span>
              {text.scanRatio} <strong>{scanRatio}%</strong>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={scanRatio}
              onChange={(event) => setScanRatio(Number(event.target.value))}
            />
          </label>
          <label>
            <span>
              {text.precisionRatio} <strong>{precisionRatio}%</strong>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={precisionRatio}
              onChange={(event) =>
                setPrecisionRatio(Number(event.target.value))
              }
            />
          </label>
          <label className="st-planner-check">
            <input
              type="checkbox"
              checked={knowledgeOutput}
              onChange={(event) => setKnowledgeOutput(event.target.checked)}
            />
            {text.knowledgeOutput}
          </label>
        </div>
        <aside aria-live="polite">
          <span>{text.profile}</span>
          <dl>
            <div>
              <dt>{text.recommended}</dt>
              <dd>{estimate.recommended}</dd>
            </div>
            <div>
              <dt>{text.creditRange}</dt>
              <dd>
                {estimate.lower.toLocaleString(locale)}–
                {estimate.upper.toLocaleString(locale)}
              </dd>
            </div>
            <div>
              <dt>{text.maximumDraw}</dt>
              <dd>
                {estimate.upper.toLocaleString(locale)} {text.credits}
              </dd>
            </div>
          </dl>
          <p>{text.priceBook}</p>
        </aside>
      </div>
    </section>
  );
}
