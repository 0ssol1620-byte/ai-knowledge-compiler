import {
  ArrowRight,
  CheckCircle,
  FilePdf,
  FolderOpen,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

const COPY = {
  ko: {
    eyebrow: "KNOWLEDGE COMPILER",
    title: "흩어진 문서를, 검증 가능한 지식으로.",
    body: "폴더 구조를 읽고, 누락을 복구하고, 모든 결과를 원문까지 연결합니다.",
    primary: "내 문서 컴파일하기",
    secondary: "실제 원문 증명 보기",
    trust: "로컬 매니페스트 · 원문 연결 · 검증 실패 시 비공개",
  },
  en: {
    eyebrow: "KNOWLEDGE COMPILER",
    title: "Compile scattered documents into verifiable knowledge.",
    body: "Read the collection, recover what is missing, and keep every result connected to its exact source.",
    primary: "Compile your collection",
    secondary: "Inspect actual-source proof",
    trust: "Local manifest · Source-linked · Fail-closed publishing",
  },
} as const;

export function ProductFilmHero({ locale }: { locale: StructaraLocale }) {
  const copy = COPY[locale];
  return (
    <section className={styles.hero} data-scene="01-product-film">
      <div className={styles.heroCopy}>
        <p>{copy.eyebrow}</p>
        <h1>{copy.title}</h1>
        <span>{copy.body}</span>
        <div className={styles.actions}>
          <Link href="/intake" className={styles.primaryAction}>
            {copy.primary}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <Link href="#actual-source" className={styles.textAction}>
            {copy.secondary}
          </Link>
        </div>
        <small>
          <CheckCircle size={14} aria-hidden="true" />
          {copy.trust}
        </small>
      </div>
      <div
        className={styles.film}
        aria-label={
          locale === "ko" ? "제품 처리 장면" : "Product processing scene"
        }
      >
        <header>
          <span>FOLYNTA / COLLECTION 2026-Q1</span>
          <b>FIXED PUBLIC DEMO</b>
        </header>
        <div className={styles.filmBody}>
          <aside>
            <strong>
              <FolderOpen size={15} /> filings
            </strong>
            <span>01-cover.pdf</span>
            <span>02-financials.pdf</span>
            <span>03-notes.xlsx</span>
            <span>04-policy.docx</span>
          </aside>
          <div className={styles.filmDocument}>
            <div className={styles.documentTop}>
              <FilePdf size={17} />
              <span>02-financials.pdf · p.30</span>
            </div>
            <div className={styles.tablePreview}>
              <span>Revenue</span>
              <b>4,902,490,901</b>
              <i>verified</i>
              <span>Cost of sales</span>
              <b>915,603,778</b>
              <i>verified</i>
              <span>Gross profit</span>
              <b>3,986,887,123</b>
              <i>verified</i>
              <span>Missing row</span>
              <b>—</b>
              <i data-warning="true">detected</i>
            </div>
          </div>
          <div className={styles.filmProof}>
            <Warning size={16} weight="fill" />
            <small>DETECTED → RECOVERED → VERIFIED</small>
            <strong>Missing table row</strong>
            <span>Source page 30 · exact region retained</span>
            <code>receipt 20260730000413</code>
          </div>
        </div>
        <footer>Page → Structure → Evidence → Knowledge</footer>
      </div>
    </section>
  );
}
