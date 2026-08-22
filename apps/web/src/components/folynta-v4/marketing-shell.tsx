/* eslint-disable @next/next/no-html-link-for-pages -- Full document navigation crosses the route-specific CSS boundary. */
import type { ReactNode } from "react";

import { LocaleSwitcher } from "@/components/locale-switcher";
import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

export function FolyntaV4MarketingShell({
  children,
  locale,
}: {
  children: ReactNode;
  locale: StructaraLocale;
}) {
  const ko = locale === "ko";
  const links = [
    ["/product/compile", ko ? "컴파일" : "Compile"],
    ["/product/verify", ko ? "검증" : "Verify"],
    ["/security", ko ? "보안" : "Security"],
    ["/pricing", ko ? "요금" : "Pricing"],
  ] as const;

  return (
    <div className={styles.siteShell}>
      <header className={styles.siteHeader}>
        <a href="/" className={styles.wordmark}>
          <span aria-hidden="true" />
          <strong>FOLYNTA</strong>
          <small>KNOWLEDGE COMPILER</small>
        </a>
        <nav aria-label={ko ? "주요 내비게이션" : "Primary navigation"}>
          {links.map(([href, label]) => (
            <a key={href} href={href}>
              {label}
            </a>
          ))}
        </nav>
        <div className={styles.headerActions}>
          <LocaleSwitcher compact />
          <a href="/login">{ko ? "로그인" : "Sign in"}</a>
          <a href="/signup" className={styles.headerPrimary}>
            {ko ? "지식 구축 시작" : "Build knowledge"}
          </a>
        </div>
      </header>
      {children}
      <footer className={styles.siteFooter}>
        <div>
          <strong>FOLYNTA</strong>
          <span>
            {ko
              ? "사람과 AI를 위한 검증 가능한 지식 컴파일러."
              : "A verifiable knowledge compiler for people and AI."}
          </span>
        </div>
        <nav aria-label={ko ? "푸터 내비게이션" : "Footer navigation"}>
          <a href="/docs">{ko ? "문서" : "Docs"}</a>
          <a href="/benchmarks">{ko ? "벤치마크" : "Benchmarks"}</a>
          <a href="/privacy">{ko ? "개인정보" : "Privacy"}</a>
          <a href="/notices">{ko ? "고지" : "Notices"}</a>
        </nav>
        <small>© 2026 FOLYNTA · Evidence-first knowledge systems.</small>
      </footer>
    </div>
  );
}
