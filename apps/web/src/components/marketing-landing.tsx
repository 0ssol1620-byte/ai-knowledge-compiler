import {
  ArrowRight,
  CheckCircle,
  FileText,
  Graph,
  LinkSimple,
  LockKey,
  SquaresFour,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { StructaraGlyph } from "@/components/structara-glyph";
import { StructaraHeroScene } from "@/components/structara-hero";
import { StructaraMarketingShell } from "@/components/structara-marketing-shell";
import { StructaraPattern } from "@/components/structara-pattern";
import { StructaraProofDemo } from "@/components/structara-proof-demo";
import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

type HomeCopy = {
  context: string;
  heroTitle: string;
  heroIntro: string;
  build: string;
  watch: string;
  trust: string;
  outputsLabel: string;
  outputs: readonly string[];
  problemTitle: readonly [string, string];
  problemBody: string;
  rawDocuments: string;
  rawSignal: string;
  compiledKnowledge: string;
  compiledItems: readonly string[];
  compiledSignal: string;
  compilerPath: string;
  transformationTitle: string;
  chapters: readonly {
    number: string;
    title: string;
    body: string;
    signal: string;
  }[];
  publicFilingDemo: string;
  inspectTitle: string;
  inspectBody: string;
  openDart: string;
  tryDocument: string;
  pillarsTitle: string;
  pillars: readonly [string, string, string][];
  publicProofSystems: string;
  publicProofTitle: string;
  dartTitle: string;
  dartBody: string;
  dartLink: string;
  secTitle: string;
  secBody: string;
  secLink: string;
  benchmarkLabel: string;
  benchmarkTitle: string;
  benchmarkBody: string;
  metricHeaders: readonly string[];
  metrics: readonly [string, string, string][];
  benchmarkLink: string;
  useCasesTitle: string;
  useCases: readonly [string, string][];
  privateLabel: string;
  securityTitle: string;
  securityBody: string;
  securityLink: string;
  policyCenter: string;
  policies: readonly string[];
  manifesto: string;
  knowledgeStatements: readonly string[];
  compilerStatement: string;
  finalIntro: string;
  finalTitle: string;
  sales: string;
  finalTrust: string;
  exportLabel: string;
  knowledgeLabel: string;
};

const HOME_COPY: Record<StructaraLocale, HomeCopy> = {
  en: {
    context: "The Knowledge Compiler for AI",
    heroTitle: "Your AI is only as good as the knowledge it receives.",
    heroIntro:
      "Turn documents into structured, verified, connected knowledge with every important result linked back to its source.",
    build: "Build your knowledge",
    watch: "Watch the transformation",
    trust: "Source-linked · Portable · Private by policy",
    outputsLabel: "Supported outputs",
    outputs: [
      "Portable Markdown",
      "Obsidian Vault",
      "RAG JSONL",
      "Knowledge Graph",
    ],
    problemTitle: ["Powerful models.", "Weak context."],
    problemBody:
      "Complex layouts, broken tables, repeated headers, page boundaries, and summaries without sources leave AI with text but not usable knowledge.",
    rawDocuments: "Raw documents",
    rawSignal: "Fragments · repeated headers · broken table · no links",
    compiledKnowledge: "Compiled knowledge",
    compiledItems: [
      "Heading tree",
      "Table object",
      "Source link",
      "Note network",
    ],
    compiledSignal: "Structure · evidence · relationships · portable output",
    compilerPath: "The compiler path",
    transformationTitle:
      "From pages to intelligence, without losing the proof.",
    chapters: [
      {
        number: "01",
        title: "It sees more than text.",
        body: "Headings, paragraphs, tables, formulas, figures, footnotes, and reading order become one inspectable document structure.",
        signal: "Page → typed blocks",
      },
      {
        number: "02",
        title: "Every output returns to its source.",
        body: "Select a sentence, number, or table cell and return to the exact page region that produced it.",
        signal: "Result → page · block · bbox",
      },
      {
        number: "03",
        title: "Documents become a knowledge system.",
        body: "Sections become notes. Notes surface entities. Evidence-backed relations connect documents that previously stood alone.",
        signal: "Blocks → notes · entities · relations",
      },
      {
        number: "04",
        title: "Compile once. Use it everywhere.",
        body: "Portable Markdown, Obsidian, RAG JSONL, JSON-LD, and project packs derive from the same verified source map.",
        signal: "One core → many destinations",
      },
    ],
    publicFilingDemo: "Public filing demo",
    inspectTitle: "Do not take our word for it. Inspect the result.",
    inspectBody:
      "The same DART sample connects the original page, Markdown, knowledge package, graph, and proof panel.",
    openDart: "Open full DART demo",
    tryDocument: "Try it with your document",
    pillarsTitle:
      "Knowledge has structure, evidence, connection, and a way out.",
    pillars: [
      [
        "Structure",
        "Preserve hierarchy, not just characters.",
        "Heading tree + reading order",
      ],
      [
        "Evidence",
        "Trace every result back to the page.",
        "Page · block · bounding box",
      ],
      [
        "Connection",
        "Turn isolated files into a knowledge network.",
        "Notes · entities · relations",
      ],
      [
        "Portability",
        "Your knowledge should not belong to one tool.",
        "Markdown · Vault · RAG · JSON-LD",
      ],
    ],
    publicProofSystems: "Public proof systems",
    publicProofTitle:
      "Built for documents that cannot afford to be misunderstood.",
    dartTitle: "Korean financial filings",
    dartBody:
      "Long-form Korean, XML/XBRL ground truth, complex tables, metrics, risks, segments, and corrected filing relationships.",
    dartLink: "Explore DART",
    secTitle: "10-K, 10-Q, and 8-K",
    secBody:
      "Inline XBRL, risk factors, exhibits, filing relationships, and source-linked entities in the same ontology.",
    secLink: "Explore SEC",
    benchmarkLabel: "Benchmark discipline",
    benchmarkTitle: "Accuracy should be demonstrated, not declared.",
    benchmarkBody:
      "Dataset, sample count, route version, evaluator, and date travel with every result. Unmeasured values remain unavailable.",
    metricHeaders: ["Metric", "Public status", "Evidence"],
    metrics: [
      ["Text fidelity", "Not measured", "Dataset required"],
      ["Numeric preservation", "Not measured", "Ground truth required"],
      ["Table structure", "Not measured", "Comparator required"],
      ["Source coverage", "Verified locally", "Live source-link E2E"],
    ],
    benchmarkLink: "Explore benchmark methodology",
    useCasesTitle: "One compiler. Different knowledge systems.",
    useCases: [
      [
        "Research",
        "Papers become methods, datasets, results, limitations, and citation-linked notes.",
      ],
      [
        "Personal knowledge",
        "Books, lectures, and notes become an Obsidian-ready concept system.",
      ],
      [
        "Enterprise",
        "Manuals, policies, and reports remain governed by access, retention, and audit.",
      ],
      [
        "AI and RAG",
        "Source-linked chunks and JSONL arrive ready for evaluation and retrieval.",
      ],
    ],
    privateLabel: "Private by default",
    securityTitle: "Your knowledge stays yours.",
    securityBody:
      "Region, retention, access, audit, and external processing policy surround the document before a job begins.",
    securityLink: "Explore security architecture",
    policyCenter: "Document",
    policies: ["Region", "Retention", "Access", "Audit", "External AI"],
    manifesto: "AI does not need more information. It needs better knowledge.",
    knowledgeStatements: [
      "Knowledge has structure.",
      "Knowledge has context.",
      "Knowledge has relationships.",
      "Knowledge has evidence.",
    ],
    compilerStatement: "Structara compiles all four.",
    finalIntro: "Your documents already contain what your AI needs.",
    finalTitle: "Make it usable.",
    sales: "Talk to sales",
    finalTrust: "Source-linked · Portable · Policy controlled",
    exportLabel: "Export",
    knowledgeLabel: "Knowledge",
  },
  ko: {
    context: "AI를 위한 지식 컴파일러",
    heroTitle: "AI의 성능은 전달받는 지식의 품질을 넘을 수 없습니다.",
    heroIntro:
      "문서를 구조화되고 검증되며 서로 연결된 지식으로 전환하고, 중요한 모든 결과를 원본에 다시 연결합니다.",
    build: "지식 시스템 구축하기",
    watch: "변환 과정 보기",
    trust: "원본 연결 · 이식 가능 · 정책 기반 비공개",
    outputsLabel: "지원 출력",
    outputs: [
      "이식 가능한 Markdown",
      "Obsidian Vault",
      "RAG JSONL",
      "Knowledge Graph",
    ],
    problemTitle: ["강력한 모델.", "부족한 맥락."],
    problemBody:
      "복잡한 레이아웃, 깨진 표, 반복 머리글, 페이지 경계와 원본 없는 요약은 AI에 텍스트만 전달할 뿐 활용 가능한 지식을 제공하지 못합니다.",
    rawDocuments: "원본 문서",
    rawSignal: "조각난 내용 · 반복 머리글 · 깨진 표 · 연결 없음",
    compiledKnowledge: "컴파일된 지식",
    compiledItems: ["제목 계층", "표 객체", "원본 링크", "노트 네트워크"],
    compiledSignal: "구조 · 근거 · 관계 · 이식 가능한 출력",
    compilerPath: "컴파일러 경로",
    transformationTitle: "근거를 잃지 않고 페이지를 지능으로 전환합니다.",
    chapters: [
      {
        number: "01",
        title: "텍스트 너머를 이해합니다.",
        body: "제목, 문단, 표, 수식, 그림, 각주와 읽기 순서를 하나의 확인 가능한 문서 구조로 만듭니다.",
        signal: "페이지 → 타입 블록",
      },
      {
        number: "02",
        title: "모든 출력은 원본으로 돌아갑니다.",
        body: "문장, 숫자 또는 표 셀을 선택하면 그 결과를 만든 정확한 페이지 영역으로 이동합니다.",
        signal: "결과 → 페이지 · 블록 · bbox",
      },
      {
        number: "03",
        title: "문서를 지식 시스템으로 만듭니다.",
        body: "섹션은 노트가 되고, 노트는 엔티티를 드러내며, 근거가 있는 관계가 분리돼 있던 문서를 연결합니다.",
        signal: "블록 → 노트 · 엔티티 · 관계",
      },
      {
        number: "04",
        title: "한 번 컴파일하고 어디서나 사용합니다.",
        body: "동일한 검증 원본 맵에서 Markdown, Obsidian, RAG JSONL, JSON-LD와 프로젝트 패키지를 생성합니다.",
        signal: "하나의 코어 → 여러 목적지",
      },
    ],
    publicFilingDemo: "공개 공시 데모",
    inspectTitle: "설명을 믿지 말고 결과를 직접 확인하세요.",
    inspectBody:
      "동일한 DART 샘플이 원본 페이지, Markdown, 지식 패키지, 그래프와 Proof 패널을 연결합니다.",
    openDart: "전체 DART 데모 열기",
    tryDocument: "내 문서로 사용해 보기",
    pillarsTitle: "지식에는 구조, 근거, 연결과 이식 가능한 출구가 있습니다.",
    pillars: [
      ["구조", "문자만이 아니라 계층을 보존합니다.", "제목 계층 + 읽기 순서"],
      [
        "근거",
        "모든 결과를 원본 페이지까지 추적합니다.",
        "페이지 · 블록 · 바운딩 박스",
      ],
      [
        "연결",
        "분리된 파일을 지식 네트워크로 만듭니다.",
        "노트 · 엔티티 · 관계",
      ],
      [
        "이식성",
        "지식이 하나의 도구에 종속되지 않게 합니다.",
        "Markdown · Vault · RAG · JSON-LD",
      ],
    ],
    publicProofSystems: "공개 Proof 시스템",
    publicProofTitle: "오해가 허용되지 않는 문서를 위해 설계했습니다.",
    dartTitle: "한국 금융 공시",
    dartBody:
      "한국어 장문, XML/XBRL 정답 데이터, 복잡한 표, 지표, 위험, 사업 부문과 정정 공시 관계를 다룹니다.",
    dartLink: "DART 살펴보기",
    secTitle: "10-K, 10-Q와 8-K",
    secBody:
      "Inline XBRL, 위험 요인, 첨부 문서, 공시 관계와 원본 연결 엔티티를 동일한 온톨로지로 다룹니다.",
    secLink: "SEC 살펴보기",
    benchmarkLabel: "벤치마크 원칙",
    benchmarkTitle: "정확도는 선언이 아니라 근거로 증명해야 합니다.",
    benchmarkBody:
      "모든 결과에 데이터셋, 샘플 수, 처리 경로 버전, 평가기와 날짜를 함께 제공합니다. 측정하지 않은 값은 측정 불가로 유지합니다.",
    metricHeaders: ["지표", "공개 상태", "근거"],
    metrics: [
      ["텍스트 충실도", "미측정", "데이터셋 필요"],
      ["숫자 보존", "미측정", "정답 데이터 필요"],
      ["표 구조", "미측정", "비교기 필요"],
      ["원본 커버리지", "로컬 검증 완료", "원본 링크 E2E"],
    ],
    benchmarkLink: "벤치마크 방법론 살펴보기",
    useCasesTitle: "하나의 컴파일러로 서로 다른 지식 시스템을 만듭니다.",
    useCases: [
      [
        "연구",
        "논문을 방법, 데이터셋, 결과, 한계와 인용 연결 노트로 전환합니다.",
      ],
      [
        "개인 지식",
        "책, 강의와 노트를 Obsidian 호환 개념 시스템으로 전환합니다.",
      ],
      [
        "엔터프라이즈",
        "매뉴얼, 정책과 보고서를 접근, 보존과 감사 정책으로 통제합니다.",
      ],
      [
        "AI와 RAG",
        "원본 연결 청크와 JSONL을 평가 및 검색에 바로 사용할 수 있게 제공합니다.",
      ],
    ],
    privateLabel: "기본 비공개",
    securityTitle: "고객의 지식은 고객에게 남습니다.",
    securityBody:
      "작업 시작 전에 리전, 보존, 접근, 감사와 외부 처리 정책이 문서를 둘러싸고 통제합니다.",
    securityLink: "보안 아키텍처 살펴보기",
    policyCenter: "문서",
    policies: ["리전", "보존", "접근", "감사", "외부 AI"],
    manifesto: "AI에는 더 많은 정보가 아니라 더 나은 지식이 필요합니다.",
    knowledgeStatements: [
      "지식에는 구조가 있습니다.",
      "지식에는 맥락이 있습니다.",
      "지식에는 관계가 있습니다.",
      "지식에는 근거가 있습니다.",
    ],
    compilerStatement: "Structara는 이 네 가지를 모두 컴파일합니다.",
    finalIntro: "문서에는 이미 AI에 필요한 정보가 담겨 있습니다.",
    finalTitle: "활용 가능한 지식으로 만드세요.",
    sales: "영업팀 문의",
    finalTrust: "원본 연결 · 이식 가능 · 정책 통제",
    exportLabel: "내보내기",
    knowledgeLabel: "지식",
  },
};

export function MarketingLanding({
  locale = "en",
}: {
  locale?: StructaraLocale;
}) {
  const copy = HOME_COPY[locale];
  return (
    <StructaraMarketingShell>
      <main id="main-content" className="st-home">
        <section className="st-home-hero">
          <div className="st-home-copy">
            <p className="st-context-label">{copy.context}</p>
            <h1>{copy.heroTitle}</h1>
            <p className="st-home-intro">{copy.heroIntro}</p>
            <div className="st-actions">
              <Link href="/signup" className="st-button st-button-dark">
                {copy.build}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
              <a href="#transformation" className="st-text-action">
                {copy.watch}
              </a>
            </div>
            <p className="st-trust-line">{copy.trust}</p>
            <p className="st-compiler-sequence">
              Page → Structure → Evidence → Knowledge → Intelligence
            </p>
          </div>
          <StructaraHeroScene />
          <div className="st-output-rail" aria-label={copy.outputsLabel}>
            {copy.outputs.map((output) => (
              <span key={output}>{output}</span>
            ))}
          </div>
        </section>

        <section className="st-problem">
          <StructaraPattern
            name="coordinate-field"
            className="st-section-pattern st-problem-pattern"
          />
          <div>
            <h2>
              {copy.problemTitle[0]}
              <br />
              {copy.problemTitle[1]}
            </h2>
            <p>{copy.problemBody}</p>
          </div>
          <div className="st-before-after">
            <article>
              <span>{copy.rawDocuments}</span>
              <div className="st-fragments">
                <i />
                <i />
                <i />
                <i />
              </div>
              <p>{copy.rawSignal}</p>
            </article>
            <div className="st-compile-path" aria-hidden="true">
              <FileText size={16} />
              <span />
              <SquaresFour size={16} />
              <span />
              <LinkSimple size={16} />
              <span />
              <Graph size={16} />
            </div>
            <article>
              <span>{copy.compiledKnowledge}</span>
              <div className="st-compiled">
                <strong>{copy.compiledItems[0]}</strong>
                {copy.compiledItems.slice(1).map((item) => (
                  <i key={item}>{item}</i>
                ))}
              </div>
              <p>{copy.compiledSignal}</p>
            </article>
          </div>
        </section>

        <section id="transformation" className="st-transformation">
          <header>
            <p>{copy.compilerPath}</p>
            <h2>{copy.transformationTitle}</h2>
          </header>
          <div className="st-chapters">
            {copy.chapters.map((chapter) => (
              <article key={chapter.number}>
                <div className="st-chapter-copy">
                  <span>{chapter.number}</span>
                  <h3>{chapter.title}</h3>
                  <p>{chapter.body}</p>
                  <small>{chapter.signal}</small>
                </div>
                <ChapterVisual
                  index={chapter.number}
                  exportLabel={copy.exportLabel}
                  knowledgeLabel={copy.knowledgeLabel}
                />
              </article>
            ))}
          </div>
        </section>

        <section className="st-demo-section">
          <div className="st-section-intro">
            <p>{copy.publicFilingDemo}</p>
            <h2>{copy.inspectTitle}</h2>
            <span>{copy.inspectBody}</span>
          </div>
          <StructaraProofDemo />
          <div className="st-inline-actions">
            <Link href="/demo/dart">{copy.openDart}</Link>
            <Link href="/signup">{copy.tryDocument}</Link>
          </div>
        </section>

        <section className="st-pillars">
          <header>
            <h2>{copy.pillarsTitle}</h2>
          </header>
          {copy.pillars.map(([title, body, proof]) => (
            <article key={title}>
              <span>{title}</span>
              <h3>{body}</h3>
              <p>{proof}</p>
            </article>
          ))}
        </section>

        <section className="st-public-proof">
          <div className="st-section-intro">
            <p>{copy.publicProofSystems}</p>
            <h2>{copy.publicProofTitle}</h2>
          </div>
          <article>
            <span>KR · DART</span>
            <h3>{copy.dartTitle}</h3>
            <p>{copy.dartBody}</p>
            <Link href="/demo/dart">{copy.dartLink}</Link>
          </article>
          <article>
            <span>US · SEC EDGAR</span>
            <h3>{copy.secTitle}</h3>
            <p>{copy.secBody}</p>
            <Link href="/demo/sec">{copy.secLink}</Link>
          </article>
        </section>

        <section className="st-benchmark">
          <div>
            <p>{copy.benchmarkLabel}</p>
            <h2>{copy.benchmarkTitle}</h2>
            <span>{copy.benchmarkBody}</span>
          </div>
          <div className="st-metric-table">
            <div>
              {copy.metricHeaders.map((cell) => (
                <span key={cell}>{cell}</span>
              ))}
            </div>
            {copy.metrics.map((row) => (
              <div key={row[0]}>
                {row.map((cell) => (
                  <span key={cell}>{cell}</span>
                ))}
              </div>
            ))}
          </div>
          <Link href="/benchmarks" className="st-text-action">
            {copy.benchmarkLink}
          </Link>
        </section>

        <section className="st-use-cases">
          <header>
            <h2>{copy.useCasesTitle}</h2>
          </header>
          {copy.useCases.map(([title, body], index) => (
            <article key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </section>

        <section className="st-security-band">
          <div>
            <LockKey size={22} aria-hidden="true" />
            <p>{copy.privateLabel}</p>
            <h2>{copy.securityTitle}</h2>
            <span>{copy.securityBody}</span>
            <Link href="/security">{copy.securityLink}</Link>
          </div>
          <div className="st-policy-orbit">
            <strong>{copy.policyCenter}</strong>
            {copy.policies.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </section>

        <section className="st-manifesto">
          <StructaraGlyph name="verified" size={24} />
          <p>{copy.manifesto}</p>
          <div>
            {copy.knowledgeStatements.map((statement) => (
              <span key={statement}>{statement}</span>
            ))}
          </div>
          <h2>{copy.compilerStatement}</h2>
        </section>

        <section className="st-home-final">
          <p>{copy.finalIntro}</p>
          <h2>{copy.finalTitle}</h2>
          <div className="st-actions">
            <Link href="/signup" className="st-button st-button-dark">
              {copy.build} <ArrowRight size={16} />
            </Link>
            <Link href="/company/contact" className="st-text-action">
              {copy.sales}
            </Link>
          </div>
          <small>
            <CheckCircle size={14} /> {copy.finalTrust}
          </small>
        </section>
      </main>
    </StructaraMarketingShell>
  );
}

function ChapterVisual({
  index,
  exportLabel,
  knowledgeLabel,
}: {
  index: string;
  exportLabel: string;
  knowledgeLabel: string;
}) {
  const glyph =
    index === "01"
      ? "block"
      : index === "02"
        ? "evidence"
        : index === "03"
          ? "node"
          : "package";
  return (
    <div className={`st-chapter-visual st-chapter-${index}`} aria-hidden="true">
      <StructaraGlyph name={glyph} size={26} />
      <div className="st-visual-page">
        <i />
        <i />
        <i />
        <b />
      </div>
      <div className="st-visual-result">
        <strong>
          {index === "02"
            ? DART_PUBLIC_FIXTURE.rows[0].current
            : index === "04"
              ? exportLabel
              : knowledgeLabel}
        </strong>
        <span />
        <span />
      </div>
      <div className="st-visual-link" />
    </div>
  );
}
