import { ArrowRight, CheckCircle } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

export function KnowledgeFormation({ locale }: { locale: StructaraLocale }) {
  const ko = locale === "ko";
  return (
    <>
      <section className={styles.section} data-scene="05-knowledge">
        <header className={styles.sectionHeading}>
          <p>05 · KNOWLEDGE FORMATION</p>
          <h2>
            {ko
              ? "하나의 검증 결과가, 연결된 지식 체계로 자랍니다."
              : "One verified result becomes a connected knowledge system."}
          </h2>
          <span>
            {ko
              ? "폴더, 노트, 관계와 내보내기는 모두 같은 근거 레코드를 가리킵니다."
              : "Folders, notes, relations, and exports all resolve to the same evidence record."}
          </span>
        </header>
        <div className={styles.formationFrame}>
          <aside>
            <small>VAULT TREE</small>
            <strong>JTC / 2026 / Q1</strong>
            <span>Financial statements</span>
            <b>Revenue.md</b>
            <span>Cost of sales.md</span>
          </aside>
          <article>
            <small>ATOMIC NOTE</small>
            <h3>JTC — 2026 Q1 revenue</h3>
            <p>Consolidated revenue was 4,902,490,901 JPY.</p>
            <dl>
              <div>
                <dt>period</dt>
                <dd>2026 Q1</dd>
              </div>
              <div>
                <dt>source</dt>
                <dd>page 30</dd>
              </div>
              <div>
                <dt>receipt</dt>
                <dd>20260730000413</dd>
              </div>
            </dl>
          </article>
          <div
            className={styles.graphStage}
            aria-label={
              ko ? "접근 가능한 관계 그래프" : "Accessible relation graph"
            }
          >
            <small>LOCAL GRAPH</small>
            <span>JTC</span>
            <i />
            <span>Revenue</span>
            <i />
            <span>2026 Q1</span>
            <p>JTC — reported → Revenue — period → 2026 Q1</p>
          </div>
        </div>
      </section>
      <section
        className={`${styles.section} ${styles.trustSection}`}
        data-scene="06-trust"
      >
        <header className={styles.sectionHeading}>
          <p>06 · TRUST</p>
          <h2>
            {ko
              ? "검증할 수 없는 결과는, 완료로 표시하지 않습니다."
              : "If a result cannot be verified, it is not labeled complete."}
          </h2>
          <span>
            {ko
              ? "Verified, Recovered & Verified, Unresolved, Excluded의 네 상태가 발행 경계를 결정합니다."
              : "Verified, Recovered & Verified, Unresolved, and Excluded define the publish boundary."}
          </span>
        </header>
        <div className={styles.trustMatrix}>
          {[
            ["Verified", "source + validators"],
            ["Recovered & Verified", "repair + re-verification"],
            ["Unresolved", "visible, not published"],
            ["Excluded", "policy-bound, counted"],
          ].map(([title, detail], index) => (
            <div key={title} data-pass={index < 2}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{title}</strong>
              <small>{detail}</small>
            </div>
          ))}
        </div>
      </section>
      <section className={styles.finalCta} data-scene="07-final">
        <p>07 · BEGIN</p>
        <h2>
          {ko
            ? "문서를 업로드하세요. 근거는 끝까지 남습니다."
            : "Bring your documents. Keep the evidence all the way through."}
        </h2>
        <span>
          {ko
            ? "로컬 매니페스트와 검증 가능한 첫 결과로 시작합니다."
            : "Start with a local manifest and a verifiable first result."}
        </span>
        <div className={styles.actions}>
          <Link href="/intake" className={styles.primaryAction}>
            {ko ? "내 문서 컴파일하기" : "Compile your collection"}
            <ArrowRight size={16} />
          </Link>
          <Link href="/benchmarks" className={styles.textAction}>
            {ko ? "측정 방법 보기" : "Review methodology"}
          </Link>
        </div>
        <small>
          <CheckCircle size={14} />
          Source-linked by design
        </small>
      </section>
    </>
  );
}
