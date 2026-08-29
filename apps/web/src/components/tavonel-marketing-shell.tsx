"use client";

import { CaretDown, List, X } from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { useStructaraLocale } from "@/components/locale-provider";

const KO_LABELS: Record<string, string> = {
  Product: "제품",
  Overview: "개요",
  Convert: "변환",
  Verify: "검증",
  Knowledge: "지식",
  Graph: "그래프",
  Connect: "연결",
  Solutions: "솔루션",
  Individuals: "개인",
  Research: "연구",
  Teams: "팀",
  Developers: "개발자",
  Enterprise: "엔터프라이즈",
  Demo: "데모",
  Security: "보안",
  Pricing: "요금",
  Workspace: "워크스페이스",
};

const groups = {
  Product: [
    ["/product", "Overview"],
    ["/product/convert", "Convert"],
    ["/product/verify", "Verify"],
    ["/product/knowledge", "Knowledge"],
    ["/product/graph", "Graph"],
    ["/product/connect", "Connect"],
  ],
  Solutions: [
    ["/solutions/individuals", "Individuals"],
    ["/solutions/research", "Research"],
    ["/solutions/teams", "Teams"],
    ["/solutions/developers", "Developers"],
    ["/solutions/enterprise", "Enterprise"],
  ],
} as const;

export function TavonelMarketingShell({ children }: { children: ReactNode }) {
  const { locale } = useStructaraLocale();
  const korean = locale === "ko";
  const label = (value: string) =>
    korean ? (KO_LABELS[value] ?? value) : value;
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
        <nav
          className="tv-desktop-nav"
          aria-label={korean ? "주요 내비게이션" : "Primary navigation"}
        >
          {Object.entries(groups).map(([label, links]) => (
            <div className="tv-nav-group" key={label}>
              <Link
                className="tv-nav-trigger"
                href={links[0][0] as Route}
                aria-haspopup="true"
                aria-label={
                  korean
                    ? `${KO_LABELS[label] ?? label} 개요 및 하위 메뉴`
                    : `${label} overview and submenu`
                }
              >
                {korean ? (KO_LABELS[label] ?? label) : label}
                <CaretDown size={13} aria-hidden="true" />
              </Link>
              <div className="tv-nav-panel">
                {links.map(([href, item]) => (
                  <Link key={href} href={href}>
                    <span>{korean ? (KO_LABELS[item] ?? item) : item}</span>
                    <small>
                      {korean
                        ? item === "Overview"
                          ? "전체 컴파일러 워크플로"
                          : `${KO_LABELS[item] ?? item} 살펴보기`
                        : item === "Overview"
                          ? "The complete compiler workflow"
                          : `Explore ${item.toLowerCase()}`}
                    </small>
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <Link href="/demo">{label("Demo")}</Link>
          <Link href="/research">{label("Research")}</Link>
          <Link href="/security">{label("Security")}</Link>
          <Link href="/pricing">{label("Pricing")}</Link>
        </nav>
        <div className="tv-header-actions">
          <Link href="/login" className="tv-text-link">
            {korean ? "로그인" : "Sign in"}
          </Link>
          <Link href="/signup" className="tv-button tv-button-dark">
            {korean ? "지식 만들기" : "Build your knowledge"}
          </Link>
          <LocaleSwitcher compact />
          <button
            type="button"
            className="tv-menu-button"
            aria-label={
              open
                ? korean
                  ? "내비게이션 닫기"
                  : "Close navigation"
                : korean
                  ? "내비게이션 열기"
                  : "Open navigation"
            }
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={20} /> : <List size={20} />}
          </button>
        </div>
      </header>
      {open && (
        <nav
          className="tv-mobile-nav"
          aria-label={korean ? "모바일 내비게이션" : "Mobile navigation"}
        >
          <LocaleSwitcher compact />
          {Object.entries(groups).map(([label, links]) => (
            <section key={label}>
              <p>{korean ? (KO_LABELS[label] ?? label) : label}</p>
              {links.map(([href, item]) => (
                <Link key={href} href={href}>
                  {korean ? (KO_LABELS[item] ?? item) : item}
                </Link>
              ))}
            </section>
          ))}
          {(
            [
              ["/demo", "Demo"],
              ["/research", "Research"],
              ["/security", "Security"],
              ["/pricing", "Pricing"],
              ["/app/home", "Workspace"],
            ] as const
          ).map(([href, label]) => (
            <Link key={href} href={href as Route}>
              {korean ? (KO_LABELS[label] ?? label) : label}
            </Link>
          ))}
        </nav>
      )}
      {children}
      <footer className="tv-footer">
        <div className="tv-footer-cta">
          <p>
            {korean
              ? "AI에 필요한 지식은 이미 문서 안에 있습니다."
              : "Your documents already contain what your AI needs."}
          </p>
          <h2>
            {korean
              ? "TAVONEL이 쓸 수 있게 만듭니다."
              : "TAVONEL makes it usable."}
          </h2>
          <div>
            <Link href="/signup" className="tv-button tv-button-light">
              {korean ? "지식 만들기" : "Build your knowledge"}
            </Link>
            <Link href="/company/contact" className="tv-footer-link">
              {korean ? "도입 상담" : "Talk to sales"}
            </Link>
          </div>
        </div>
        <div className="tv-footer-grid">
          <div className="tv-footer-brand">
            <BrandMark />
            <p>
              {korean
                ? "모든 원본에서 지식까지 이어지는 추적 가능한 경로."
                : "A traceable path from every source to knowledge."}
            </p>
            {/* Still true, and §25.7 forbids removing a disclosure that has
                not become false. Trademark clearance is open — decision.md G-A. */}
            <small>
              {korean
                ? "TAVONEL은 상표 확인이 진행 중인 작업명입니다."
                : "TAVONEL is a working name pending brand clearance."}
            </small>
          </div>
          {[
            [
              "Product",
              [
                "/product/convert",
                "/product/verify",
                "/product/knowledge",
                "/product/graph",
              ],
            ],
            [
              "Solutions",
              [
                "/solutions/individuals",
                "/solutions/research",
                "/solutions/teams",
                "/solutions/enterprise",
              ],
            ],
            [
              "Resources",
              [
                "/demo",
                "/benchmarks",
                "/developers/docs",
                "/developers/changelog",
              ],
            ],
            [
              "Company",
              [
                "/company/about",
                "/company/principles",
                "/company/careers",
                "/company/contact",
              ],
            ],
            [
              "Legal",
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
          <span>The Knowledge Compiler for AI</span>
        </div>
      </footer>
    </div>
  );
}
