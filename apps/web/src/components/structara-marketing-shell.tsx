"use client";

import { CaretDown, List, X } from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { useStructaraLocale } from "@/components/locale-provider";

const routeGroups = {
  product: [
    ["/product", "overview"],
    ["/product/convert", "convert"],
    ["/product/verify", "verify"],
    ["/product/knowledge", "knowledge"],
    ["/product/graph", "graph"],
    ["/product/connect", "connect"],
  ],
  solutions: [
    ["/solutions/individuals", "individuals"],
    ["/solutions/research", "research"],
    ["/solutions/teams", "teams"],
    ["/solutions/developers", "developers"],
    ["/solutions/enterprise", "enterprise"],
  ],
} as const;

const labels = {
  en: {
    product: "Product",
    solutions: "Solutions",
    overview: "Overview",
    convert: "Convert",
    verify: "Verify",
    knowledge: "Knowledge",
    graph: "Graph",
    connect: "Connect",
    individuals: "Individuals",
    research: "Research",
    teams: "Teams",
    developers: "Developers",
    enterprise: "Enterprise",
    demo: "Demo",
    security: "Security",
    pricing: "Pricing",
    signIn: "Sign in",
    build: "Build your knowledge",
    openNav: "Open navigation",
    closeNav: "Close navigation",
    primaryNav: "Primary navigation",
    mobileNav: "Mobile navigation",
    overviewDescription: "The complete compiler workflow",
    explore: "Explore",
    workspace: "Workspace",
    footerLead: "Your documents already contain what your AI needs.",
    footerTitle: "FOLYNTA makes it usable.",
    sales: "Talk to sales",
    brandBody:
      "Structured, verified, connected, portable knowledge for people and AI.",
    copyright: "© 2026 FOLYNTA. Evidence-first knowledge systems.",
    productFooter: "Product",
    solutionsFooter: "Solutions",
    resources: "Resources",
    company: "Company",
    legal: "Legal",
    productTagline: "From every page, a system of knowledge.",
    footerLinks: {
      convert: "convert",
      verify: "verify",
      knowledge: "knowledge",
      graph: "graph",
      individuals: "individuals",
      research: "research",
      teams: "teams",
      enterprise: "enterprise",
      demo: "demo",
      benchmarks: "benchmarks",
      docs: "developer docs",
      changelog: "changelog",
      about: "about",
      principles: "principles",
      careers: "careers",
      contact: "contact",
      privacy: "privacy",
      terms: "terms",
      subprocessors: "subprocessors",
      notices: "third-party notices",
    },
  },
  ko: {
    product: "제품",
    solutions: "솔루션",
    overview: "개요",
    convert: "변환",
    verify: "검증",
    knowledge: "지식",
    graph: "그래프",
    connect: "연결",
    individuals: "개인",
    research: "리서치",
    teams: "팀",
    developers: "개발자",
    enterprise: "엔터프라이즈",
    demo: "데모",
    security: "보안",
    pricing: "요금",
    signIn: "로그인",
    build: "지식 구축 시작",
    openNav: "내비게이션 열기",
    closeNav: "내비게이션 닫기",
    primaryNav: "주요 내비게이션",
    mobileNav: "모바일 내비게이션",
    overviewDescription: "전체 지식 컴파일 워크플로",
    explore: "살펴보기",
    workspace: "워크스페이스",
    footerLead: "AI에 필요한 정보는 이미 문서 안에 있습니다.",
    footerTitle: "FOLYNTA가 사용할 수 있는 지식으로 만듭니다.",
    sales: "도입 문의",
    brandBody: "사람과 AI를 위한 구조화·검증·연결·이식 가능한 지식.",
    copyright: "© 2026 FOLYNTA. 근거 중심 지식 시스템.",
    productFooter: "제품",
    solutionsFooter: "솔루션",
    resources: "리소스",
    company: "회사",
    legal: "법적 고지",
    productTagline: "From every page, a system of knowledge.",
    footerLinks: {
      convert: "변환",
      verify: "검증",
      knowledge: "지식",
      graph: "그래프",
      individuals: "개인",
      research: "리서치",
      teams: "팀",
      enterprise: "엔터프라이즈",
      demo: "데모",
      benchmarks: "벤치마크",
      docs: "개발자 문서",
      changelog: "변경 이력",
      about: "소개",
      principles: "원칙",
      careers: "채용",
      contact: "문의",
      privacy: "개인정보 처리 원칙",
      terms: "이용약관",
      subprocessors: "하위 처리업체",
      notices: "제3자 고지",
    },
  },
} as const;

export function StructaraMarketingShell({
  children,
  showFooterCta = true,
}: {
  children: ReactNode;
  showFooterCta?: boolean;
}) {
  const { locale } = useStructaraLocale();
  const copy = locale === "ko" ? labels.ko : labels.en;
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const groups = useMemo(
    () => [
      {
        key: "product" as const,
        label: copy.product,
        links: routeGroups.product,
      },
      {
        key: "solutions" as const,
        label: copy.solutions,
        links: routeGroups.solutions,
      },
    ],
    [copy.product, copy.solutions],
  );

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 24);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("st-menu-open", open);
    return () => document.body.classList.remove("st-menu-open");
  }, [open]);

  return (
    <div className="st-site">
      <header className="st-header" data-scrolled={scrolled}>
        <Link href="/" className="st-logo-link">
          <BrandMark />
        </Link>
        <nav className="st-desktop-nav" aria-label={copy.primaryNav}>
          {groups.map(({ key, label, links }) => (
            <div className="st-nav-group" key={key}>
              <Link
                className="st-nav-trigger"
                href={links[0][0] as Route}
                aria-haspopup="true"
                aria-label={`${label} ${copy.overview}`}
              >
                {label}
                <CaretDown size={13} aria-hidden="true" />
              </Link>
              <div className="st-nav-panel">
                {links.map(([href, item]) => (
                  <Link key={href} href={href}>
                    <span>{copy[item]}</span>
                    <small>
                      {item === "overview"
                        ? copy.overviewDescription
                        : `${copy.explore} ${copy[item]}`}
                    </small>
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <Link href="/demo">{copy.demo}</Link>
          <Link href="/research">{copy.research}</Link>
          <Link href="/security">{copy.security}</Link>
          <Link href="/pricing">{copy.pricing}</Link>
        </nav>
        <div className="st-header-actions">
          <LocaleSwitcher compact className="st-locale-switcher" />
          <Link href="/login" className="st-text-link">
            {copy.signIn}
          </Link>
          <Link href="/signup" className="st-button st-button-dark">
            {copy.build}
          </Link>
          <button
            type="button"
            className="st-menu-button"
            aria-label={open ? copy.closeNav : copy.openNav}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={20} /> : <List size={20} />}
          </button>
        </div>
      </header>
      {open && (
        <nav className="st-mobile-nav" aria-label={copy.mobileNav}>
          <LocaleSwitcher className="st-mobile-locale-switcher" />
          {groups.map(({ key, label, links }) => (
            <section key={key}>
              <p>{label}</p>
              {links.map(([href, item]) => (
                <Link key={href} href={href} onClick={() => setOpen(false)}>
                  {copy[item]}
                </Link>
              ))}
            </section>
          ))}
          {(
            [
              ["/demo", copy.demo],
              ["/research", copy.research],
              ["/security", copy.security],
              ["/pricing", copy.pricing],
              ["/app/home", copy.workspace],
            ] as const
          ).map(([href, label]) => (
            <Link
              key={href}
              href={href as Route}
              onClick={() => setOpen(false)}
            >
              {label}
            </Link>
          ))}
        </nav>
      )}
      {children}
      <footer className="st-footer">
        {showFooterCta && <div className="st-footer-cta">
          <p>{copy.footerLead}</p>
          <h2>{copy.footerTitle}</h2>
          <div>
            <Link href="/signup" className="st-button st-button-light">
              {copy.build}
            </Link>
            <Link href="/company/contact" className="st-footer-link">
              {copy.sales}
            </Link>
          </div>
        </div>}
        <div className="st-footer-grid">
          <div className="st-footer-brand">
            <BrandMark />
            <p>{copy.brandBody}</p>
            <small>{copy.copyright}</small>
          </div>
          {[
            [
              copy.productFooter,
              [
                ["/product/convert", copy.footerLinks.convert],
                ["/product/verify", copy.footerLinks.verify],
                ["/product/knowledge", copy.footerLinks.knowledge],
                ["/product/graph", copy.footerLinks.graph],
              ],
            ],
            [
              copy.solutionsFooter,
              [
                ["/solutions/individuals", copy.footerLinks.individuals],
                ["/solutions/research", copy.footerLinks.research],
                ["/solutions/teams", copy.footerLinks.teams],
                ["/solutions/enterprise", copy.footerLinks.enterprise],
              ],
            ],
            [
              copy.resources,
              [
                ["/demo", copy.footerLinks.demo],
                ["/benchmarks", copy.footerLinks.benchmarks],
                ["/developers/docs", copy.footerLinks.docs],
                ["/developers/changelog", copy.footerLinks.changelog],
              ],
            ],
            [
              copy.company,
              [
                ["/company/about", copy.footerLinks.about],
                ["/company/principles", copy.footerLinks.principles],
                ["/company/careers", copy.footerLinks.careers],
                ["/company/contact", copy.footerLinks.contact],
              ],
            ],
            [
              copy.legal,
              [
                ["/legal/privacy", copy.footerLinks.privacy],
                ["/legal/terms", copy.footerLinks.terms],
                ["/legal/subprocessors", copy.footerLinks.subprocessors],
                ["/legal/third-party-notices", copy.footerLinks.notices],
              ],
            ],
          ].map(([heading, links]) => (
            <nav key={heading as string} aria-label={`${heading}`}>
              <strong>{heading as string}</strong>
              {(links as unknown as readonly (readonly [string, string])[]).map(
                ([href, label]) => (
                  <Link key={href} href={href as Route}>
                    {label}
                  </Link>
                ),
              )}
            </nav>
          ))}
        </div>
        <div className="st-footer-meta">
          <span>© 2026 FOLYNTA</span>
          <span>{copy.productTagline}</span>
        </div>
      </footer>
    </div>
  );
}
