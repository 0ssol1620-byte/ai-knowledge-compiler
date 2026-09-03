"use client";

import { CaretDown, List, X } from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useStructaraLocale } from "@/components/locale-provider";
import { LocaleSwitcher } from "@/components/locale-switcher";

const groups = {
  Product: [
    ["/product", "Overview"],
    ["/product/knowledge-compiler", "Knowledge Compiler"],
    ["/product/document-understanding", "Document Understanding"],
    ["/product/compiled-world", "Compiled World"],
    ["/product/grounded-ai", "Grounded AI"],
  ],
  Solutions: [
    ["/solutions/ai-ready-knowledge", "AI-ready knowledge"],
    ["/solutions/document-intelligence", "Document intelligence"],
    ["/solutions/knowledge-graph", "Knowledge graph"],
    ["/solutions/source-grounded-assistants", "Grounded assistants"],
    ["/solutions/knowledge-operations", "Knowledge operations"],
  ],
} as const;

const resourceLinks = [
  ["/demo", "Product proof"],
  ["/research", "Research"],
  ["/developers/docs", "Documentation"],
  ["/developers/changelog", "Changelog"],
] as const;

const SHELL_COPY = {
  en: {
    product: "Product", solutions: "Solutions", integrations: "Integrations",
    developers: "Developers", security: "Security", pricing: "Pricing",
    resources: "Resources", signIn: "Sign in", build: "Build your knowledge",
    open: "Open navigation", close: "Close navigation", primary: "Primary navigation",
    mobile: "Mobile navigation", overview: "Overview", workflow: "The complete compiler workflow",
    explore: "Explore", inspect: "Inspect source-verifiable material", workspace: "Workspace",
    footerLead: "Your documents already contain what your AI needs.",
    footerTitle: "TAVONEL makes it usable.", sales: "Talk to sales",
    promise: "A traceable path from every source to knowledge.",
    clearance: "TAVONEL is a working name pending brand clearance.",
    company: "Company", legal: "Legal", compiler: "The Knowledge Compiler for AI",
  },
  ko: {
    product: "제품", solutions: "솔루션", integrations: "연동",
    developers: "개발자", security: "보안", pricing: "가격",
    resources: "자료", signIn: "로그인", build: "지식 구축하기",
    open: "내비게이션 열기", close: "내비게이션 닫기", primary: "주요 내비게이션",
    mobile: "모바일 내비게이션", overview: "개요", workflow: "전체 컴파일러 워크플로",
    explore: "살펴보기", inspect: "원본 검증 가능한 자료 살펴보기", workspace: "워크스페이스",
    footerLead: "문서에는 이미 AI가 필요로 하는 지식이 담겨 있습니다.",
    footerTitle: "TAVONEL이 그 지식을 사용할 수 있게 만듭니다.", sales: "도입 문의",
    promise: "모든 원본에서 지식까지 이어지는 추적 가능한 경로.",
    clearance: "TAVONEL은 브랜드 권리 확인 중인 작업명입니다.",
    company: "회사", legal: "법률", compiler: "AI를 위한 Knowledge Compiler",
  },
} as const;

const KOREAN_LABELS: Record<string, string> = {
  Overview: "개요", "Knowledge Compiler": "Knowledge Compiler",
  "Document Understanding": "문서 이해", "Compiled World": "Compiled World",
  "Grounded AI": "근거 기반 AI", "AI-ready knowledge": "AI 준비 지식",
  "Document intelligence": "문서 인텔리전스", "Knowledge graph": "지식 그래프",
  "Grounded assistants": "근거 기반 어시스턴트", "Knowledge operations": "지식 운영",
  "Product proof": "제품 증거", Research: "연구", Documentation: "문서", Changelog: "변경 기록",
};

export function TavonelMarketingShell({ children }: { children: ReactNode }) {
  const { locale } = useStructaraLocale();
  const copy = SHELL_COPY[locale];
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 24);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("tv-menu-open", open);
    return () => document.body.classList.remove("tv-menu-open");
  }, [open]);

  return (
    <div className="tv-site">
      <header className="tv-header" data-scrolled={scrolled}>
        <Link href="/" className="tv-logo-link">
          <BrandMark />
        </Link>
        <nav className="tv-desktop-nav" aria-label={copy.primary}>
          {Object.entries(groups).map(([label, links]) => (
            <div className="tv-nav-group" key={label}>
              <Link
                className="tv-nav-trigger"
                href={links[0][0] as Route}
                aria-haspopup="true"
                aria-label={`${label === "Product" ? copy.product : copy.solutions} ${copy.overview}`}
              >
                {label === "Product" ? copy.product : copy.solutions}
                <CaretDown size={13} aria-hidden="true" />
              </Link>
              <div className="tv-nav-panel">
                {links.map(([href, item]) => (
                  <Link key={href} href={href}>
                    <span>{locale === "ko" ? KOREAN_LABELS[item] : item}</span>
                    <small>
                      {item === "Overview"
                        ? copy.workflow
                        : `${copy.explore} ${locale === "ko" ? KOREAN_LABELS[item] : item.toLowerCase()}`}
                    </small>
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <Link href="/integrations">{copy.integrations}</Link>
          <Link href="/developers">{copy.developers}</Link>
          <Link href="/security">{copy.security}</Link>
          <Link href="/pricing">{copy.pricing}</Link>
          <div className="tv-nav-group">
            <Link className="tv-nav-trigger" href="/demo" aria-haspopup="true">
              {copy.resources} <CaretDown size={13} aria-hidden="true" />
            </Link>
            <div className="tv-nav-panel">
              {resourceLinks.map(([href, item]) => (
                <Link key={href} href={href}>
                  <span>{locale === "ko" ? KOREAN_LABELS[item] : item}</span><small>{copy.inspect}</small>
                </Link>
              ))}
            </div>
          </div>
        </nav>
        <div className="tv-header-actions">
          <LocaleSwitcher compact className="tv-locale-switcher" />
          <Link href="/login" className="tv-text-link">
            {copy.signIn}
          </Link>
          <Link href="/signup" className="tv-button tv-button-dark">
            {copy.build}
          </Link>
          <button
            type="button"
            className="tv-menu-button"
            aria-label={open ? copy.close : copy.open}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={20} /> : <List size={20} />}
          </button>
        </div>
      </header>
      {open && (
        <nav className="tv-mobile-nav" aria-label={copy.mobile}>
          <LocaleSwitcher compact className="tv-mobile-locale-switcher" />
          {Object.entries(groups).map(([label, links]) => (
            <section key={label}>
              <p>{label === "Product" ? copy.product : copy.solutions}</p>
              {links.map(([href, item]) => (
                <Link key={href} href={href}>
                  {locale === "ko" ? KOREAN_LABELS[item] : item}
                </Link>
              ))}
            </section>
          ))}
          <section>
            <p>{copy.resources}</p>
            {resourceLinks.map(([href, item]) => <Link key={href} href={href}>{locale === "ko" ? KOREAN_LABELS[item] : item}</Link>)}
          </section>
          {(
            [
              ["/integrations", copy.integrations],
              ["/developers", copy.developers],
              ["/security", copy.security],
              ["/pricing", copy.pricing],
              ["/app/home", copy.workspace],
            ] as const
          ).map(([href, label]) => (
            <Link key={href} href={href as Route}>
              {label}
            </Link>
          ))}
        </nav>
      )}
      {children}
      <footer className="tv-footer">
        <div className="tv-footer-cta">
          <p>{copy.footerLead}</p>
          <h2>{copy.footerTitle}</h2>
          <div>
            <Link href="/signup" className="tv-button tv-button-light">
              {copy.build}
            </Link>
            <Link href="/company/contact" className="tv-footer-link">
              {copy.sales}
            </Link>
          </div>
        </div>
        <div className="tv-footer-grid">
          <div className="tv-footer-brand">
            <BrandMark />
            <p>
              {copy.promise}
            </p>
            {/* Still true, and §25.7 forbids removing a disclosure that has
                not become false. Trademark clearance is open — decision.md G-A. */}
            <small>{copy.clearance}</small>
          </div>
          {[
            [
              copy.product,
              [
                "/product/convert",
                "/product/verify",
                "/product/knowledge",
                "/product/graph",
              ],
            ],
            [
              copy.solutions,
              [
                "/solutions/individuals",
                "/solutions/research",
                "/solutions/teams",
                "/solutions/enterprise",
              ],
            ],
            [
              copy.resources,
              [
                "/demo",
                "/research",
                "/developers/docs",
                "/developers/changelog",
              ],
            ],
            [
              copy.company,
              [
                "/company/about",
                "/company/principles",
                "/company/careers",
                "/company/contact",
              ],
            ],
            [
              copy.legal,
              [
                "/legal/privacy",
                "/legal/terms",
                "/legal/subprocessors",
                "/legal/third-party-notices",
              ],
            ],
          ].map(([heading, links]) => (
            <nav key={heading as string} aria-label={`${heading} links`}>
              <strong>{heading as string}</strong>
              {(links as string[]).map((href) => (
                <Link key={href} href={href as Route}>
                  {href.split("/").at(-1)?.replaceAll("-", " ")}
                </Link>
              ))}
            </nav>
          ))}
        </div>
        <div className="tv-footer-meta">
          <span>© 2026 TAVONEL</span>
          <span>{copy.compiler}</span>
        </div>
      </footer>
    </div>
  );
}
