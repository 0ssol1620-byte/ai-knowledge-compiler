import {
  CheckCircle,
  File,
  Folder,
  Hash,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";

import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

export function IntakeCinematic({ locale }: { locale: StructaraLocale }) {
  const ko = locale === "ko";
  return (
    <section className={styles.section} data-scene="02-intake">
      <header className={styles.sectionHeading}>
        <p>02 · INTAKE</p>
        <h2>
          {ko
            ? "폴더를 업로드하면, 먼저 구조부터 이해합니다."
            : "Upload a folder. FOLYNTA understands its structure first."}
        </h2>
        <span>
          {ko
            ? "브라우저에서 만든 로컬 매니페스트가 경로, 크기, 해시를 고정합니다. 파일 내용은 검증 전까지 결과로 승격되지 않습니다."
            : "A browser-built local manifest pins paths, sizes, and hashes. No content is promoted before verification."}
        </span>
      </header>
      <div className={styles.intakeFrame}>
        <div className={styles.fileTree}>
          <strong>
            <Folder size={16} /> investor-relations
          </strong>
          {[
            ["2026-Q1/financials.pdf", "2.17 MB"],
            ["2026-Q1/notes.xlsx", "184 KB"],
            ["policies/retention.docx", "92 KB"],
            ["research/methodology.md", "31 KB"],
          ].map(([name, size]) => (
            <span key={name}>
              <File size={14} />
              {name}
              <small>{size}</small>
            </span>
          ))}
        </div>
        <div className={styles.manifestPanel}>
          <header>
            <span>LOCAL MANIFEST</span>
            <b>4 files · 4 source hashes</b>
          </header>
          <dl>
            <div>
              <dt>
                <Hash size={14} /> Integrity
              </dt>
              <dd>SHA-256 bound</dd>
            </div>
            <div>
              <dt>
                <ShieldCheck size={14} /> Policy
              </dt>
              <dd>Private · Seoul</dd>
            </div>
            <div>
              <dt>
                <CheckCircle size={14} /> Duplicate scan
              </dt>
              <dd>0 conflicts</dd>
            </div>
          </dl>
          <p>
            {ko
              ? "표시된 값은 고정 공개 데모 매니페스트이며 업로드 진행률이 아닙니다."
              : "Values describe a fixed public demo manifest; they are not upload progress."}
          </p>
        </div>
      </div>
    </section>
  );
}
