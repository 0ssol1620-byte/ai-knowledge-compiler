import { ArrowRight, CheckCircle, LockKey } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { TransformationStory } from "@/components/marketing/transformation-story";
import { StructaraHeroScene } from "@/components/structara-hero";
import { StructaraMarketingShell } from "@/components/structara-marketing-shell";
import { StructaraProofDemo } from "@/components/structara-proof-demo";
import {
  formatBenchmarkCost,
  formatBenchmarkLatency,
  formatBenchmarkPercent,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";
import { PUBLIC_BRAND } from "@/lib/brand";
import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

const COPY = {
  en: {
    hero: PUBLIC_BRAND.english.hero,
    intro: PUBLIC_BRAND.english.category,
    proof: PUBLIC_BRAND.english.proof,
    primary: "Compile your collection",
    secondary: "Inspect the public proof",
    trust: "Source-linked · Portable · Private by policy",
    proofLabel: "02 · Full-bleed proof",
    proofTitle: "Select the result. Return to the exact source cell.",
    proofBody:
      "One frozen public filing connects source PDF evidence, structured output, metadata, a portable note, and a graph relation.",
    transformationLabel: "03 · Compiler transformation",
    transformationTitle: "Understand. Verify. Connect. Activate.",
    knowledgeLabel: "04 · Knowledge system",
    knowledgeTitle: "One verified fixture. Four reusable views.",
    knowledgeBody:
      "The vault tree, atomic note, local graph, and export all resolve to the same evidence record.",
    qualityLabel: "05 · Quality and routing",
    qualityTitle: "Measured on a fixed subset. Never promoted by marketing.",
    qualityBody:
      "These are formal inference results from the frozen 18-page OmniDocBench demo subset—not a full public benchmark and not a production promotion decision.",
    securityLabel: "06 · Security and control",
    securityTitle: "Policy surrounds the document before processing begins.",
    securityBody: PUBLIC_BRAND.english.enterprise,
    policyRail: ["Region", "Retention", "Access", "Audit", "External AI"],
    finalLabel: "07 · Begin",
    finalTitle: "Turn your documents into a system of knowledge.",
    finalBody:
      "Start with a local manifest, a calibrated estimate, and a source-linked result—or review the enterprise control model first.",
    sales: "Review enterprise controls",
    benchmark: "Open methodology and evidence",
  },
  ko: {
    hero: PUBLIC_BRAND.korean.hero,
    intro: PUBLIC_BRAND.korean.category,
    proof: PUBLIC_BRAND.korean.proof,
    primary: "컬렉션 컴파일하기",
    secondary: "공개 근거 확인하기",
    trust: "원본 연결 · 이식 가능 · 정책 기반 비공개",
    proofLabel: "02 · 전체 폭 Proof",
    proofTitle: "결과를 선택하면 정확한 원문 셀로 돌아갑니다.",
    proofBody:
      "하나의 고정 공개 공시가 원문 PDF 근거, 구조화 결과, 메타데이터, 이식 가능한 노트와 그래프 관계를 연결합니다.",
    transformationLabel: "03 · 컴파일러 변환",
    transformationTitle: "이해하고, 검증하고, 연결하고, 활성화합니다.",
    knowledgeLabel: "04 · 지식 시스템",
    knowledgeTitle: "하나의 검증 픽스처를 네 가지 방식으로 재사용합니다.",
    knowledgeBody:
      "Vault 트리, 원자 노트, 로컬 그래프와 내보내기가 모두 같은 근거 레코드로 돌아갑니다.",
    qualityLabel: "05 · 품질과 라우팅",
    qualityTitle: "고정 부분집합에서 측정하며, 마케팅으로 승격하지 않습니다.",
    qualityBody:
      "고정된 OmniDocBench 공식 데모 18페이지에서 수행한 정식 추론 결과입니다. 전체 공개 벤치마크도, 프로덕션 승격 결정도 아닙니다.",
    securityLabel: "06 · 보안과 제어",
    securityTitle: "처리 전에 정책이 문서를 먼저 둘러쌉니다.",
    securityBody: PUBLIC_BRAND.korean.enterprise,
    policyRail: ["리전", "보존", "접근", "감사", "외부 AI"],
    finalLabel: "07 · 시작",
    finalTitle: "문서를 하나의 지식 시스템으로 만드세요.",
    finalBody:
      "로컬 매니페스트, 보정된 예상치와 원문 연결 결과로 시작하거나 엔터프라이즈 제어 모델을 먼저 검토하세요.",
    sales: "엔터프라이즈 제어 검토",
    benchmark: "방법론과 근거 열기",
  },
} as const;

const TRANSFORMATION = {
  en: [
    ["01", "Understand", "Recover reading order, hierarchy, tables, figures, formulas, and footnotes as typed blocks.", "Page → semantic blocks"],
    ["02", "Verify", "Bind claims, numbers, and cells to page, block, bounding box, and immutable receipt.", "Block → evidence"],
    ["03", "Connect", "Compile sections into notes, entities, relations, and continuity across documents.", "Evidence → knowledge"],
    ["04", "Activate", "Derive Markdown, Vault, RAG JSONL, JSON-LD, and project packs from one verified core.", "One core → many uses"],
  ],
  ko: [
    ["01", "이해", "읽기 순서, 계층, 표, 그림, 수식과 각주를 타입이 있는 블록으로 복원합니다.", "페이지 → 의미 블록"],
    ["02", "검증", "주장, 숫자와 셀을 페이지, 블록, 바운딩 박스와 불변 영수증에 결합합니다.", "블록 → 근거"],
    ["03", "연결", "섹션을 노트, 엔티티, 관계와 문서 간 연속성으로 컴파일합니다.", "근거 → 지식"],
    ["04", "활성화", "하나의 검증 코어에서 Markdown, Vault, RAG JSONL, JSON-LD와 프로젝트 팩을 파생합니다.", "하나의 코어 → 여러 활용"],
  ],
} as const;

export function MarketingLanding({ locale = "en" }: { locale?: StructaraLocale }) {
  const copy = COPY[locale];
  const candidates = publicBenchmarkSnapshot.datasets.filter(
    (dataset) => dataset.status === "available",
  );
  const revenue = DART_PUBLIC_FIXTURE.rows[0];
  const chapters = TRANSFORMATION[locale].map(([number, title, body, signal]) => ({
    id: `compiler-${number}`,
    number,
    title,
    body,
    signal,
  }));

  return (
    <StructaraMarketingShell showFooterCta={false}>
      <main id="main-content" className="st-home folynta-home">
        <section className="st-home-hero folynta-scene" data-scene="01-hero">
          <div className="st-home-copy">
            <p className="st-context-label">{PUBLIC_BRAND.category}</p>
            <h1>{copy.hero}</h1>
            <p className="st-home-intro">{copy.intro}</p>
            <p className="folynta-proof-line">{copy.proof}</p>
            <div className="st-actions">
              <Link href="/intake" className="st-button st-button-dark">
                {copy.primary}<ArrowRight size={16} aria-hidden="true" />
              </Link>
              <Link href="#proof" className="st-text-action">{copy.secondary}</Link>
            </div>
            <p className="st-trust-line">{copy.trust}</p>
            <p className="st-compiler-sequence">Page → Structure → Evidence → Knowledge → Intelligence</p>
          </div>
          <StructaraHeroScene locale={locale} />
        </section>

        <section id="proof" className="folynta-proof-scene folynta-scene" data-scene="02-proof">
          <header className="folynta-section-heading">
            <p>{copy.proofLabel}</p><h2>{copy.proofTitle}</h2><span>{copy.proofBody}</span>
          </header>
          <StructaraProofDemo locale={locale} />
        </section>

        <TransformationStory locale={locale} chapters={chapters} />

        <section className="folynta-knowledge-scene folynta-scene" data-scene="04-knowledge">
          <header className="folynta-section-heading">
            <p>{copy.knowledgeLabel}</p><h2>{copy.knowledgeTitle}</h2><span>{copy.knowledgeBody}</span>
          </header>
          <div className="folynta-knowledge-grid">
            <article><small>VAULT TREE</small><strong>JTC / 2026 / Q1</strong><span>Financial statements</span><b>Revenue.md</b></article>
            <article><small>ATOMIC NOTE</small><strong>{revenue.label}</strong><span>{revenue.current} {DART_PUBLIC_FIXTURE.unit}</span><code>receipt: {DART_PUBLIC_FIXTURE.receiptNumber}</code></article>
            <article className="folynta-graph"><small>LOCAL GRAPH</small><div><span>JTC</span><i /><span>Revenue</span></div><code>evidence: source line {revenue.sourceLine}</code></article>
            <article><small>EXPORT</small><strong>Verified core</strong><span>Markdown · Vault · RAG JSONL</span><span>JSON-LD · Knowledge package</span></article>
          </div>
        </section>

        <section className="folynta-quality-scene folynta-scene" data-scene="05-quality">
          <header className="folynta-section-heading">
            <p>{copy.qualityLabel}</p><h2>{copy.qualityTitle}</h2><span>{copy.qualityBody}</span>
          </header>
          <div className="folynta-benchmark-table" role="table" aria-label={copy.qualityTitle}>
            <div role="row"><strong role="columnheader">Candidate</strong><strong role="columnheader">Text 1−edit</strong><strong role="columnheader">Table TEDS</strong><strong role="columnheader">Runtime</strong><strong role="columnheader">Est. cost/page</strong></div>
            {candidates.map((dataset) => <div role="row" key={dataset.id}>
              <span role="cell">{dataset.label}</span>
              <span role="cell">{formatBenchmarkPercent(dataset.metrics.text_edit_companion)}</span>
              <span role="cell">{formatBenchmarkPercent(dataset.metrics.table_teds)}</span>
              <span role="cell">{formatBenchmarkLatency(dataset.metrics.mean_latency_ms)}</span>
              <span role="cell">{formatBenchmarkCost(dataset.metrics.cost_per_page_usd)}</span>
            </div>)}
          </div>
          <div className="folynta-quality-footer"><span>SHADOW · 18-page fixed subset · RTX 4090 · $0.69/h · no public parser promoted</span><Link href="/benchmarks">{copy.benchmark}</Link></div>
        </section>

        <section className="folynta-security-scene folynta-scene" data-scene="06-security">
          <header className="folynta-section-heading"><p>{copy.securityLabel}</p><h2>{copy.securityTitle}</h2><span>{copy.securityBody}</span></header>
          <div className="folynta-security-layout">
            <div className="folynta-security-flow" aria-label="Verified document processing flow">
              {[
                ["Browser", "Local manifest"], ["Quarantine", "Hash + scan"], ["Verified Source", "Immutable receipt"],
                ["Isolated Worker", "Tenant-scoped"], ["Derived Knowledge", "Source-linked"], ["Purge", "Retention policy"],
              ].map(([title, detail], index) => <div key={title}><span>{String(index + 1).padStart(2, "0")}</span><strong>{title}</strong><small>{detail}</small></div>)}
            </div>
            <aside><LockKey size={22} aria-hidden="true" /><strong>POLICY RAIL</strong>{copy.policyRail.map((policy) => <span key={policy}>{policy}<CheckCircle size={14} aria-hidden="true" /></span>)}<Link href="/security">Security architecture</Link></aside>
          </div>
        </section>

        <section className="st-home-final folynta-scene" data-scene="07-final">
          <p>{copy.finalLabel}</p><h2>{copy.finalTitle}</h2><span>{copy.finalBody}</span>
          <div className="st-actions"><Link href="/intake" className="st-button st-button-dark">{copy.primary}<ArrowRight size={16} aria-hidden="true" /></Link><Link href="/company/contact" className="st-text-action">{copy.sales}</Link></div>
          <small><CheckCircle size={14} aria-hidden="true" /> {PUBLIC_BRAND.tagline}</small>
        </section>
      </main>
    </StructaraMarketingShell>
  );
}
