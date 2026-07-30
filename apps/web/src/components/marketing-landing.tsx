import {
  ArrowRight,
  BracketsCurly,
  ChartScatter,
  Check,
  FileArrowDown,
  FileText,
  FlowArrow,
  Graph,
  LockKey,
  ShieldCheck,
  Stack,
  Table,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import {
  formatBenchmarkPercent,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";

const proofSteps = [
  {
    title: "페이지를 구조로 읽습니다",
    copy: "텍스트만 추출하지 않고 제목, 표, 그림, 수식과 읽기 순서를 원본 좌표와 함께 복원합니다.",
    icon: FileText,
    signal: "문단 · 표 · 수식 · 이미지",
  },
  {
    title: "결과를 원문과 검증합니다",
    copy: "숫자와 표 구조, 출처 범위를 확인하고 불확실한 항목만 위험도 순으로 검토합니다.",
    icon: ShieldCheck,
    signal: "숫자 · 구조 · 출처 검사",
  },
  {
    title: "재사용 가능한 지식으로 컴파일합니다",
    copy: "검증된 블록에서 노트, 엔터티, 관계를 만들고 모든 주장에 근거 체인을 남깁니다.",
    icon: Graph,
    signal: "노트 · 엔터티 · 관계",
  },
  {
    title: "어디서나 쓰는 패키지로 내보냅니다",
    copy: "Portable Markdown, Obsidian Vault, RAG JSONL과 JSON-LD를 같은 원본에서 생성합니다.",
    icon: FileArrowDown,
    signal: "Markdown · Vault · RAG · JSON-LD",
  },
] as const;

export function MarketingLanding() {
  return (
    <div className="marketing-site">
      <header className="marketing-nav">
        <Link href="/" className="marketing-brand">
          <BrandMark />
        </Link>
        <nav aria-label="마케팅 메뉴">
          <a href="#product">제품</a>
          <a href="#demo">데모</a>
          <a href="#benchmark">벤치마크</a>
          <a href="#security">보안</a>
          <a href="#pricing">가격</a>
          <Link href="/notices">문서</Link>
        </nav>
        <div>
          <Link href="/login" className="marketing-signin">
            로그인
          </Link>
          <Link href="/home" className="primary-button marketing-cta">
            무료로 시작
          </Link>
        </div>
      </header>

      <main id="main-content">
        <section className="marketing-hero">
          <div className="hero-copy">
            <h1>
              모든 문서를,
              <br />
              검증 가능한 AI 지식으로.
            </h1>
            <p>
              PDF·보고서·논문·강의자료를 원문 근거가 연결된 Markdown, Obsidian
              Vault, RAG 데이터, 지식 그래프로 변환합니다.
            </p>
            <div className="hero-actions">
              <Link href="/home" className="primary-button hero-primary">
                내 문서로 시작하기
                <ArrowRight size={17} aria-hidden="true" />
              </Link>
              <a href="#demo" className="secondary-button hero-secondary">
                실제 변환 과정 보기
              </a>
            </div>
            <div className="hero-trust" aria-label="제품 신뢰 원칙">
              {[
                "원문 근거 연결",
                "실시간 처리 공개",
                "외부 AI 전송 선택",
                "자동 삭제 설정",
              ].map((item) => (
                <span key={item}>
                  <Check size={13} weight="bold" aria-hidden="true" />
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div
            className="compiler-scene"
            aria-label="문서가 지식으로 변환되는 정적 시각화"
          >
            <div className="scene-grid" aria-hidden="true" />
            <div className="scene-label scene-label-source">Source pages</div>
            <div className="scene-label scene-label-result">
              Verified output
            </div>
            <div className="page-plane page-plane-back">
              <i />
              <i />
              <i />
            </div>
            <div className="page-plane page-plane-mid">
              <i />
              <i />
              <i />
              <i />
            </div>
            <div className="page-plane page-plane-front">
              <span>Annual report</span>
              <i className="scene-heading" />
              <i />
              <i className="scene-table" />
              <i />
            </div>
            <div className="typed-block block-heading">Heading</div>
            <div className="typed-block block-table">
              <Table size={13} aria-hidden="true" />
              Table
            </div>
            <div className="typed-block block-metric">샘플 값</div>
            <div className="markdown-plane">
              <div className="markdown-title">
                <BracketsCurly size={15} aria-hidden="true" />
                verified-output.md
              </div>
              <strong># Revenue overview</strong>
              <span>Source-linked financial result</span>
              <div className="markdown-table">
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
              </div>
              <small>
                <ShieldCheck size={12} weight="fill" aria-hidden="true" />
                Evidence coverage verified
              </small>
            </div>
            <svg
              className="provenance-thread provenance-one"
              viewBox="0 0 180 80"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path d="M2 68 C60 68 96 15 178 15" />
            </svg>
            <svg
              className="provenance-thread provenance-two"
              viewBox="0 0 200 110"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path d="M2 20 C72 20 110 94 198 94" />
            </svg>
            <div className="knowledge-node node-company">Company</div>
            <div className="knowledge-node node-metric">Metric</div>
            <div className="knowledge-node node-evidence">Evidence</div>
            <span className="scene-status">
              <span aria-hidden="true" />
              Deterministic sample replay
            </span>
          </div>
        </section>

        <section className="product-truth-strip" aria-label="제품 결과 형식">
          <span>Portable Markdown</span>
          <span>Obsidian Vault</span>
          <span>RAG JSONL</span>
          <span>JSON-LD</span>
          <span>Source map</span>
          <span>Quality report</span>
        </section>

        <section className="transformation-story" id="product">
          <header>
            <h2>파일을 변환하는 것이 아니라, 지식의 근거를 컴파일합니다.</h2>
            <p>
              각 단계는 실제 처리 객체와 이벤트에 연결됩니다. 결과를 클릭하면
              언제든 원본 페이지와 좌표로 돌아갈 수 있습니다.
            </p>
          </header>
          <div className="proof-step-grid">
            {proofSteps.map((step) => {
              const Icon = step.icon;
              return (
                <article key={step.title}>
                  <div>
                    <Icon size={21} weight="duotone" aria-hidden="true" />
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                  <small>{step.signal}</small>
                </article>
              );
            })}
          </div>
        </section>

        <section className="interactive-proof" id="demo">
          <div className="proof-copy">
            <h2>원본에서 결과까지, 한 번의 클릭으로 검증합니다.</h2>
            <p>
              샘플 재생은 production event contract를 사용합니다. 실제 작업처럼
              페이지 상태, 블록 생성, 품질 경고와 지식 노드가 순서대로
              반영됩니다.
            </p>
            <ul>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                원본 표 셀과 Markdown 행을 연결
              </li>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                AI 요약과 원문 추출을 분리 표시
              </li>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                그래프 관계에서 근거 PDF로 역추적
              </li>
            </ul>
            <Link href="/workspace" className="text-link">
              Processing Studio 열기
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
          <div className="product-proof-frame">
            <div className="proof-frame-topbar">
              <span />
              <strong>evidence-grounded-report.pdf</strong>
              <small>샘플 문서 · 14쪽</small>
            </div>
            <div className="proof-stage-rail">
              {["Upload", "Preflight", "Parse", "Normalize", "Knowledge"].map(
                (stage, index) => (
                  <span data-state={index < 3 ? "done" : "next"} key={stage}>
                    <i>{index < 3 ? "✓" : index + 1}</i>
                    {stage}
                  </span>
                ),
              )}
            </div>
            <div className="proof-workspace">
              <aside>
                {[12, 13, 14, 15].map((page) => (
                  <div
                    className={page === 14 ? "active" : undefined}
                    key={page}
                  >
                    <span>Page {page}</span>
                    <i>{page === 14 ? "Review 1" : "Native"}</i>
                  </div>
                ))}
              </aside>
              <div className="proof-source">
                <span>ORIGINAL · PAGE 14</span>
                <strong>Consolidated revenue</strong>
                <p>
                  The reported consolidated revenue increased during the fiscal
                  period.
                </p>
                <div className="proof-source-table">
                  <span>당기 샘플</span>
                  <strong>1,234</strong>
                  <span>전기 샘플</span>
                  <strong>1,102</strong>
                </div>
                <i className="proof-bbox">table · source verified</i>
              </div>
              <div className="proof-result">
                <span>MARKDOWN · LIVE RESULT</span>
                <strong># Consolidated revenue</strong>
                <p>
                  The reported consolidated revenue increased during the fiscal
                  period.
                </p>
                <code>| 당기 샘플 | 1,234 |</code>
                <small>
                  <ShieldCheck size={12} weight="fill" aria-hidden="true" />
                  데모 값 일치 · 실제 성능 측정 아님
                </small>
              </div>
            </div>
          </div>
        </section>

        <section className="benchmark-section" id="benchmark">
          <header>
            <h2>평균 하나로 품질을 숨기지 않습니다.</h2>
            <p>문서 유형과 평가 방법, 비용·지연·출처 범위를 함께 공개합니다.</p>
          </header>
          <div className="benchmark-grid">
            <div className="benchmark-matrix">
              <div className="benchmark-head">
                <span>Document subset</span>
                <span>Text</span>
                <span>Numbers</span>
                <span>Tables</span>
                <span>Source</span>
              </div>
              {publicBenchmarkSnapshot.datasets.map((dataset) => (
                <div key={dataset.id}>
                  <span>{dataset.label}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.text)}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.numbers)}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.tables)}</span>
                  <span>
                    {formatBenchmarkPercent(dataset.metrics.provenance)}
                  </span>
                </div>
              ))}
            </div>
            <article className="benchmark-method">
              <ChartScatter size={24} weight="duotone" aria-hidden="true" />
              <h3>증거가 없으면 수치도 없습니다.</h3>
              <p>
                점수는 dataset revision, evaluator version과 route profile에
                고정됩니다. 측정하지 못한 값은 0이 아니라 unavailable로
                표시합니다.
              </p>
              <Link href="/benchmarks" className="text-link">
                Benchmark Lab 열기
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </article>
          </div>
        </section>

        <section className="security-product-section" id="security">
          <div>
            <h2>보안 문구가 아니라, 실제 통제 화면으로 증명합니다.</h2>
            <p>
              보존 기간, 처리 리전, 외부 provider, 감사 이벤트를 워크스페이스
              정책으로 관리합니다.
            </p>
          </div>
          <div className="policy-preview">
            <div>
              <LockKey size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>External provider</strong>
                <small>Admin approval only</small>
              </span>
              <i>Restricted</i>
            </div>
            <div>
              <Stack size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>Source retention</strong>
                <small>Automatic deletion</small>
              </span>
              <i>30 days</i>
            </div>
            <div>
              <FlowArrow size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>Processing region</strong>
                <small>Fail closed outside policy</small>
              </span>
              <i>Seoul</i>
            </div>
            <div>
              <ShieldCheck size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>Audit evidence</strong>
                <small>Every review and export action</small>
              </span>
              <i>Enabled</i>
            </div>
          </div>
        </section>

        <section className="pricing-section" id="pricing">
          <header>
            <h2>필요한 처리 깊이에 맞춰 시작하세요.</h2>
          </header>
          <div className="pricing-grid">
            {[
              {
                name: "Free",
                copy: "작은 문서를 검증 가능한 Markdown으로",
                items: ["Fast pages", "Portable Markdown", "7-day retention"],
              },
              {
                name: "Pro",
                copy: "연구와 개인 지식 워크플로를 위한 정밀 처리",
                items: [
                  "Precision processing",
                  "Obsidian Vault",
                  "RAG package",
                ],
                featured: true,
              },
              {
                name: "Team",
                copy: "리뷰, 지식베이스와 운영 통제가 필요한 팀",
                items: ["Shared projects", "Review workflow", "Audit history"],
              },
              {
                name: "Enterprise",
                copy: "SSO, 리전, 보존 정책과 전용 운영이 필요한 조직",
                items: ["SSO & MFA", "Provider policy", "Private deployment"],
              },
            ].map((plan) => (
              <article
                className={plan.featured ? "featured" : undefined}
                key={plan.name}
              >
                {plan.featured && <span>Recommended</span>}
                <h3>{plan.name}</h3>
                <p>{plan.copy}</p>
                <ul>
                  {plan.items.map((item) => (
                    <li key={item}>
                      <Check size={13} weight="bold" aria-hidden="true" />
                      {item}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/home"
                  className={
                    plan.featured ? "primary-button" : "secondary-button"
                  }
                >
                  {plan.name === "Enterprise" ? "문의하기" : "시작하기"}
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section className="closing-cta">
          <h2>첫 문서부터 근거가 남는 지식으로 만드세요.</h2>
          <Link href="/home" className="primary-button hero-primary">
            무료로 시작
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </section>
      </main>

      <footer className="marketing-footer">
        <div>
          <BrandMark />
          <p>문서에서 근거가 있는 AI 지식까지.</p>
        </div>
        <nav aria-label="푸터 메뉴">
          <a href="#product">Product</a>
          <a href="#benchmark">Benchmark</a>
          <a href="#security">Security</a>
          <Link href="/notices">Third-party notices</Link>
          <Link href="/login">Sign in</Link>
        </nav>
        <small>
          © 2026 AI Knowledge Compiler. 측정되지 않은 성능은 수치로 표시하지
          않습니다.
        </small>
      </footer>
    </div>
  );
}
