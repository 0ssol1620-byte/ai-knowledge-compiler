import { ArrowRight, CheckCircle, LockKey } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { HeroComp, HERO_COPY, type HeroCopy } from "@/components/facing/hero-comp";
import { TavonelMarketingShell } from "@/components/tavonel-marketing-shell";
import { TavonelProofDemo } from "@/components/tavonel-proof-demo";
import { TrialRunFilm } from "@/components/trial-run-film";
import { getRequestLocale } from "@/lib/locale-server";

const KOREAN_HERO_COPY: HeroCopy = {
  id: "d1",
  headline: [
    "문서와 연결된 시스템을",
    "AI가 사용할 수 있는 근거 기반 World로 바꾸세요.",
  ],
  lead: "파일을 넣으면 구조화되고 추적 가능한 지식이 나옵니다.",
};

const LANDING_COPY = {
  en: {
    structure: ["Typed blocks", "Identities", "Relations", "Ontology"],
    structureTitle: "Text becomes objects, relationships, and evidence.",
    structureBody: "Structure is shown from compiled records. The product does not draw an edge until a retained relation carries evidence.",
    provenanceTitle: "Every fact keeps its path back to the source.",
    provenancePath: ["Compiled claim", "Evidence block", "Page + bbox"],
    provenanceBody: "Source region, document version, and review state stay attached as the knowledge moves.",
    useTitle: "One compiled World. Every AI.", useAction: "See grounded AI",
    demoTitle: "Follow one value from document to proof.",
    demoBody: "Select each view in this frozen public filing sample. The receipt and source line remain visible.",
    demoAction: "Explore the full Compiled World",
    emitsTitle: "Knowledge that can leave the compiler.",
    outputs: [["Ontology", "ontology.ttl"], ["Knowledge Graph", "graph"], ["AI-ready Retrieval", "retrieval corpus"], ["Source Evidence", "provenance"], ["Portable Package", "signed package"]],
    compareTitle: "Retrieval is stronger when identity and evidence come first.",
    typical: "Typical RAG prep", typicalPath: "Files → chunks → vectors",
    tavonelPath: "Files → structure → identity → relationships → evidence → World → retrieval",
    solutionsTitle: "Four jobs. One source-grounded World.",
    solutions: [["AI-ready knowledge", "Prepare governed knowledge for models, retrieval, and agents."], ["Document intelligence", "Recover complex sources without detaching the page evidence."], ["Knowledge graph", "Connect verified entities and relations across source material."], ["Knowledge operations", "Run review, versions, activity, access, and exports together."]],
    integrationsTitle: "Start with sources this build can actually accept.",
    integrations: [["Browser file upload", "PDF and supported office, image, and HTML formats through the authenticated intake."], ["Authorized URL import", "Server-fetched source intake with URL security controls and task receipts."], ["API upload workflow", "Multipart targets, idempotency, job events, and export APIs for developers."]],
    available: "Available", integrationsAction: "Inspect integration states",
    securityTitle: "Your knowledge stays yours.",
    securityBody: "Tenant-scoped access, quarantine and CDR boundaries, explicit retention controls, source authorization, and auditable events surround each run.",
    securityAction: "Explore security architecture", source: "Source",
    policies: ["Access", "Quarantine", "Retention", "Audit", "Privacy"],
    pricingEyebrow: "12 · Simple, page-based pricing", pricingTitle: "Compile your own knowledge.",
    pricingBody: "Standard processing starts at $0.04 per page. See the estimate and maximum charge before a run begins.",
    compile: "Compile your own files", pricingAction: "See pricing", promise: "Source-grounded · Portable · Policy controlled",
  },
  ko: {
    structure: ["타입 블록", "식별자", "관계", "온톨로지"],
    structureTitle: "텍스트가 객체, 관계, 근거로 바뀝니다.",
    structureBody: "컴파일된 레코드에서 구조를 보여줍니다. 근거를 보존한 관계가 있을 때만 연결선을 만듭니다.",
    provenanceTitle: "모든 사실은 원본으로 돌아가는 경로를 유지합니다.",
    provenancePath: ["컴파일된 주장", "근거 블록", "페이지 + bbox"],
    provenanceBody: "지식이 이동해도 원본 영역, 문서 버전, 검토 상태가 함께 유지됩니다.",
    useTitle: "하나의 Compiled World. 모든 AI에서.", useAction: "근거 기반 AI 보기",
    demoTitle: "하나의 값이 문서에서 Proof가 되는 과정을 따라가세요.",
    demoBody: "고정된 공개 공시 샘플의 각 관점을 선택해 보세요. 처리 영수증과 원본 줄은 계속 표시됩니다.",
    demoAction: "전체 Compiled World 살펴보기",
    emitsTitle: "컴파일러 밖에서도 사용할 수 있는 지식.",
    outputs: [["온톨로지", "ontology.ttl"], ["지식 그래프", "graph"], ["AI 준비 검색", "retrieval corpus"], ["원본 근거", "provenance"], ["이식 가능한 패키지", "signed package"]],
    compareTitle: "식별자와 근거를 먼저 만들면 검색이 더 강해집니다.",
    typical: "일반적인 RAG 준비", typicalPath: "파일 → 청크 → 벡터",
    tavonelPath: "파일 → 구조 → 식별자 → 관계 → 근거 → World → 검색",
    solutionsTitle: "네 가지 업무. 하나의 원본 근거 World.",
    solutions: [["AI 준비 지식", "모델, 검색, 에이전트를 위한 정책 통제 지식을 준비합니다."], ["문서 인텔리전스", "페이지 근거를 분리하지 않고 복잡한 원본을 복원합니다."], ["지식 그래프", "검증된 엔티티와 관계를 원본 전반에서 연결합니다."], ["지식 운영", "검토, 버전, 활동, 접근, 내보내기를 함께 운영합니다."]],
    integrationsTitle: "현재 빌드가 실제로 받을 수 있는 원본부터 시작합니다.",
    integrations: [["브라우저 파일 업로드", "인증된 수집 화면에서 PDF와 지원되는 Office, 이미지, HTML 형식을 받습니다."], ["승인된 URL 가져오기", "URL 보안 통제와 작업 영수증을 갖춘 서버 수집을 제공합니다."], ["API 업로드 워크플로", "개발자를 위한 multipart 대상, 멱등성, 작업 이벤트, 내보내기 API를 제공합니다."]],
    available: "사용 가능", integrationsAction: "연동 상태 확인",
    securityTitle: "지식의 통제권은 고객에게 남습니다.",
    securityBody: "테넌트 범위 접근, 격리와 CDR 경계, 명시적 보존 통제, 원본 권한 확인, 감사 이벤트가 각 실행을 둘러쌉니다.",
    securityAction: "보안 아키텍처 살펴보기", source: "원본",
    policies: ["접근", "격리", "보존", "감사", "개인정보"],
    pricingEyebrow: "12 · 단순한 페이지 기반 가격", pricingTitle: "내 지식을 컴파일하세요.",
    pricingBody: "표준 처리는 페이지당 $0.04부터 시작합니다. 실행 전에 예상 금액과 최대 청구액을 확인할 수 있습니다.",
    compile: "내 파일 컴파일하기", pricingAction: "가격 보기", promise: "원본 근거 · 이식 가능 · 정책 통제",
  },
} as const;

export async function MarketingLanding() {
  const locale = await getRequestLocale();
  const copy = LANDING_COPY[locale];
  return (
    <TavonelMarketingShell>
      <main id="main-content" className="tv-home tv-competitive-home">
        <div data-scene="01-hero">
          <HeroComp
            variant="frame"
            copy={locale === "ko" ? KOREAN_HERO_COPY : HERO_COPY.d1}
            locale={locale}
            live
          />
        </div>

        <div data-scene="02-read">
          <TrialRunFilm />
        </div>

        <section className="tv-compiler-scene" data-scene="03-structure">
          <header><p>03 · Structure</p><h2>{copy.structureTitle}</h2></header>
          <div className="tv-structure-path" aria-label="Source structure path">
            {copy.structure.map((step, index) => <span key={step}><small>0{index + 1}</small>{step}</span>)}
          </div>
          <p>{copy.structureBody}</p>
        </section>

        <section className="tv-compiler-scene tv-provenance-scene" data-scene="04-provenance">
          <header><p>04 · Provenance</p><h2>{copy.provenanceTitle}</h2></header>
          <div><span>{copy.provenancePath[0]}</span><ArrowRight size={18} /><span>{copy.provenancePath[1]}</span><ArrowRight size={18} /><span>{copy.provenancePath[2]}</span></div>
          <p>{copy.provenanceBody}</p>
        </section>

        <section className="tv-compiler-scene tv-use-scene" data-scene="05-use">
          <header><p>05 · Use</p><h2>{copy.useTitle}</h2></header>
          <div>{["Ask", "API", "MCP", "Retrieval", "Export"].map((use) => <span key={use}>{use}</span>)}</div>
          <Link href="/product/grounded-ai">{copy.useAction} <ArrowRight size={15} /></Link>
        </section>

        <section className="tv-demo-section" data-scene="06-product-proof">
          <div className="tv-section-intro">
            <p>06 · Interactive sample</p>
            <h2>{copy.demoTitle}</h2>
            <span>{copy.demoBody}</span>
          </div>
          <TavonelProofDemo />
          <div className="tv-inline-actions"><Link href="/demo/dart">{copy.demoAction}</Link></div>
        </section>

        <section className="tv-compiler-scene tv-emits-scene" data-scene="07-emits">
          <header><p>07 · What TAVONEL emits</p><h2>{copy.emitsTitle}</h2></header>
          <div>{copy.outputs.map(([label, file]) => <article key={label}><strong>{label}</strong><code>{file}</code></article>)}</div>
        </section>

        <section className="tv-compiler-scene tv-compare-scene" data-scene="08-compile-first">
          <header><p>08 · Why compile before retrieval</p><h2>{copy.compareTitle}</h2></header>
          <div>
            <article><small>{copy.typical}</small><strong>{copy.typicalPath}</strong></article>
            <article><small>TAVONEL</small><strong>{copy.tavonelPath}</strong></article>
          </div>
        </section>

        <section className="tv-use-cases" data-scene="09-solutions">
          <header><p>09 · Solutions</p><h2>{copy.solutionsTitle}</h2></header>
          {copy.solutions.map(([title, body], index) => <article key={title}><span>0{index + 1}</span><h3>{title}</h3><p>{body}</p></article>)}
        </section>

        <section className="tv-compiler-scene tv-integrations-scene" data-scene="10-integrations">
          <header><p>10 · Integrations</p><h2>{copy.integrationsTitle}</h2></header>
          <div>
            {copy.integrations.map(([title, body]) => <article key={title}><strong>{title}</strong><span>{copy.available}</span><p>{body}</p></article>)}
          </div>
          <Link href="/integrations">{copy.integrationsAction} <ArrowRight size={15} /></Link>
        </section>

        <section className="tv-security-band" data-scene="11-security">
          <div>
            <LockKey size={22} aria-hidden="true" />
            <p>11 · Security</p><h2>{copy.securityTitle}</h2>
            <span>{copy.securityBody}</span>
            <Link href="/security">{copy.securityAction}</Link>
          </div>
          <div className="tv-policy-orbit"><strong>{copy.source}</strong>{copy.policies.map((item) => <span key={item}>{item}</span>)}</div>
        </section>

        <section className="tv-home-final" data-scene="12-pricing">
          <p>{copy.pricingEyebrow}</p><h2>{copy.pricingTitle}</h2>
          <span>{copy.pricingBody}</span>
          <div className="tv-actions">
            <Link href="/signup" className="tv-button tv-button-dark">{copy.compile} <ArrowRight size={16} /></Link>
            <Link href="/pricing" className="tv-text-action">{copy.pricingAction}</Link>
          </div>
          <small><CheckCircle size={14} /> {copy.promise}</small>
        </section>
      </main>
    </TavonelMarketingShell>
  );
}
