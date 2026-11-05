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

export function TavonelMarketingShell({ children }: { children: ReactNode }) {
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
        <nav className="tv-desktop-nav" aria-label="Primary navigation">
          {Object.entries(groups).map(([label, links]) => (
            <div className="tv-nav-group" key={label}>
              <Link
                className="tv-nav-trigger"
                href={links[0][0] as Route}
                aria-haspopup="true"
                aria-label={`${label} overview and submenu`}
              >
                {label}
                <CaretDown size={13} aria-hidden="true" />
              </Link>
              <div className="tv-nav-panel">
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
        <div className="tv-header-actions">
          <Link href="/login" className="tv-text-link">
            Sign in
          </Link>
          <Link href="/signup" className="tv-button tv-button-dark">
            Build your knowledge
          </Link>
          <button
            type="button"
            className="tv-menu-button"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={20} /> : <List size={20} />}
          </button>
        </div>
      </header>
      {open && (
        <nav className="tv-mobile-nav" aria-label="Mobile navigation">
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
      <footer className="tv-footer">
        <div className="tv-footer-cta">
          <p>Your documents already contain what your AI needs.</p>
          <h2>TAVONEL makes it usable.</h2>
          <div>
            <Link href="/signup" className="tv-button tv-button-light">
              Build your knowledge
            </Link>
            <Link href="/company/contact" className="tv-footer-link">
              Talk to sales
            </Link>
          </div>
        </div>
        <div className="tv-footer-grid">
          <div className="tv-footer-brand">
            <BrandMark />
            <p>
              A traceable path from every source to knowledge.
            </p>
            {/* Still true, and §25.7 forbids removing a disclosure that has
                not become false. Trademark clearance is open — decision.md G-A. */}
            <small>TAVONEL is a working name pending brand clearance.</small>
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
