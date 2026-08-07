"use client";

import { CaretDown, List, X } from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";

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

export function FolyntaMarketingShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 24);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("fl-menu-open", open);
    return () => document.body.classList.remove("fl-menu-open");
  }, [open]);

  return (
    <div className="fl-site">
      <header className="fl-header" data-scrolled={scrolled}>
        <Link href="/" className="fl-logo-link">
          <BrandMark />
        </Link>
        <nav className="fl-desktop-nav" aria-label="Primary navigation">
          {Object.entries(groups).map(([label, links]) => (
            <div className="fl-nav-group" key={label}>
              <Link
                className="fl-nav-trigger"
                href={links[0][0] as Route}
                aria-haspopup="true"
                aria-label={`${label} overview and submenu`}
              >
                {label}
                <CaretDown size={13} aria-hidden="true" />
              </Link>
              <div className="fl-nav-panel">
                {links.map(([href, item]) => (
                  <Link key={href} href={href}>
                    <span>{item}</span>
                    <small>
                      {item === "Overview"
                        ? "The complete compiler workflow"
                        : `Explore ${item.toLowerCase()}`}
                    </small>
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <Link href="/demo">Demo</Link>
          <Link href="/research">Research</Link>
          <Link href="/security">Security</Link>
          <Link href="/pricing">Pricing</Link>
        </nav>
        <div className="fl-header-actions">
          <Link href="/login" className="fl-text-link">
            Sign in
          </Link>
          <Link href="/signup" className="fl-button fl-button-dark">
            Build your knowledge
          </Link>
          <button
            type="button"
            className="fl-menu-button"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={20} /> : <List size={20} />}
          </button>
        </div>
      </header>
      {open && (
        <nav className="fl-mobile-nav" aria-label="Mobile navigation">
          {Object.entries(groups).map(([label, links]) => (
            <section key={label}>
              <p>{label}</p>
              {links.map(([href, item]) => (
                <Link key={href} href={href}>
                  {item}
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
              {label}
            </Link>
          ))}
        </nav>
      )}
      {children}
      <footer className="fl-footer">
        <div className="fl-footer-cta">
          <p>Your documents already contain what your AI needs.</p>
          <h2>FOLYNTA makes it usable.</h2>
          <div>
            <Link href="/signup" className="fl-button fl-button-light">
              Build your knowledge
            </Link>
            <Link href="/company/contact" className="fl-footer-link">
              Talk to sales
            </Link>
          </div>
        </div>
        <div className="fl-footer-grid">
          <div className="fl-footer-brand">
            <BrandMark />
            <p>
              Structured, verified, connected, portable knowledge for people and
              AI.
            </p>
            <small>FOLYNTA is a working name pending brand clearance.</small>
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
        <div className="fl-footer-meta">
          <span>© 2026 FOLYNTA</span>
          <span>The Knowledge Compiler for AI</span>
        </div>
      </footer>
    </div>
  );
}
