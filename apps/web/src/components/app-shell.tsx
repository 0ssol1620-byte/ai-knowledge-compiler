"use client";

import {
  ArrowLeft,
  Bell,
  BracketsCurly,
  CaretDown,
  CreditCard,
  Flask,
  FolderOpen,
  GearSix,
  House,
  Lightning,
  Lifebuoy,
  MagnifyingGlass,
  Pulse,
  ShieldCheck,
  SidebarSimple,
  TreeStructure,
  X,
} from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { normalizeSessionResponse, type SessionProfile } from "@/lib/session";

const navigation = [
  { href: "/home", label: "Overview", icon: House },
  { href: "/projects", label: "Projects", icon: FolderOpen },
  { href: "/quick-convert", label: "Quick convert", icon: Lightning },
  { href: "/knowledge-bases", label: "Knowledge", icon: TreeStructure },
  { href: "/benchmarks", label: "Benchmarks", icon: Flask },
  { href: "/api-workflows", label: "API & workflows", icon: BracketsCurly },
] as const;

const secondaryNavigation = [
  { href: "/activity", label: "Activity", icon: Pulse },
  { href: "/usage", label: "Usage", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: GearSix },
] as const;

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [sessionState, setSessionState] = useState<
    "checking" | "ready" | "denied" | "error"
  >(DEMO_MODE ? "ready" : "checking");
  const [sessionAttempt, setSessionAttempt] = useState(0);
  const [sessionError, setSessionError] = useState<string>();
  const [profile, setProfile] = useState<SessionProfile>();
  const [commandOpen, setCommandOpen] = useState(false);
  const setSession = useAuthStore((state) => state.setSession);

  const marketingRoute = pathname === "/";
  const publicRoute =
    marketingRoute ||
    pathname === "/login" ||
    pathname === "/verify-email" ||
    pathname.startsWith("/notices");

  useEffect(() => {
    if (DEMO_MODE || publicRoute) {
      return;
    }
    const controller = new AbortController();
    void apiRequest<unknown>("/v1/auth/session", {
      signal: controller.signal,
    })
      .then(normalizeSessionResponse)
      .then((result) => {
        setProfile(result);
        setSession({
          tenantId: result.tenantId,
          userName: result.displayName,
          email: result.email,
          emailVerified: result.emailVerified,
          roles: result.roles,
        });
        setSessionState("ready");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (
          reason instanceof ApiError &&
          (reason.status === 401 || reason.status === 403)
        ) {
          setSessionState("denied");
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        setSessionError(
          reason instanceof Error
            ? reason.message
            : "An unknown error occurred while checking your session.",
        );
        setSessionState("error");
      });
    return () => controller.abort();
  }, [pathname, publicRoute, router, sessionAttempt, setSession]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
      if (event.key === "Escape") setCommandOpen(false);
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  if (marketingRoute) {
    return children;
  }

  if (pathname === "/login" || pathname === "/verify-email") {
    return <main id="main-content">{children}</main>;
  }

  if (!publicRoute && sessionState !== "ready") {
    return (
      <main
        id="main-content"
        className="session-gate"
        aria-busy={sessionState === "checking"}
      >
        {sessionState === "checking" && (
          <span className="spinner" aria-hidden="true" />
        )}
        <p>
          {sessionState === "denied"
            ? "Redirecting to sign in."
            : sessionState === "error"
              ? `We could not verify your session: ${sessionError ?? "Check your connection."}`
              : "Checking your session."}
        </p>
        {sessionState === "error" && (
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              setSessionError(undefined);
              setSessionState("checking");
              setSessionAttempt((attempt) => attempt + 1);
            }}
          >
            Try again
          </button>
        )}
      </main>
    );
  }

  const workspaceName = DEMO_MODE ? "Sample workspace" : profile?.workspaceName;
  const userRole = DEMO_MODE ? "Demo" : profile?.roles[0];
  const userInitials = (DEMO_MODE ? "DE" : (profile?.displayName ?? "—"))
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className={clsx("app-frame", collapsed && "sidebar-collapsed")}>
      {DEMO_MODE && (
        <div className="demo-mode-banner" role="status">
          Demo workspace · No documents are processed and no credits are used.
        </div>
      )}
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sidebar-brand-row">
          <Link
            href="/"
            className="brand-link"
            aria-label="Return to product site"
          >
            <BrandMark compact={collapsed} />
          </Link>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setCollapsed((value) => !value)}
          >
            <SidebarSimple size={18} weight="regular" />
          </button>
        </div>

        <nav className="sidebar-nav">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={clsx("nav-item", active && "active")}
                aria-current={active ? "page" : undefined}
                title={collapsed ? label : undefined}
              >
                <Icon size={19} weight="regular" aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />

        <div className="privacy-card">
          <ShieldCheck size={18} aria-hidden="true" />
          <div>
            <strong>External processing</strong>
            <span>
              {DEMO_MODE
                ? "External APIs off"
                : profile?.externalProcessingEnabled === true
                  ? "Consent enabled"
                  : profile?.externalProcessingEnabled === false
                    ? "External APIs off"
                    : "Policy review required"}
            </span>
          </div>
        </div>

        <nav
          className="sidebar-secondary"
          aria-label="Workspace administration"
        >
          {secondaryNavigation.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                href={href}
                className={clsx("nav-item", active && "active")}
                aria-current={active ? "page" : undefined}
                title={collapsed ? label : undefined}
                key={href}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
          <Link
            href="/notices"
            className="nav-item"
            title={collapsed ? "Help and notices" : undefined}
          >
            <Lifebuoy size={19} aria-hidden="true" />
            <span>Help & notices</span>
          </Link>
          <Link
            href="/"
            className="nav-item product-site-nav"
            title={collapsed ? "Product site" : undefined}
          >
            <ArrowLeft size={19} aria-hidden="true" />
            <span>Product site</span>
          </Link>
        </nav>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-leading">
            <Link href="/" className="product-back-link">
              <ArrowLeft size={15} aria-hidden="true" />
              <span>Product site</span>
            </Link>
            <button
              type="button"
              className="topbar-search"
              onClick={() => setCommandOpen(true)}
              aria-haspopup="dialog"
            >
              <MagnifyingGlass size={17} aria-hidden="true" />
              <span>Search projects, documents, or evidence</span>
              <kbd>Ctrl K</kbd>
            </button>
          </div>
          <div className="topbar-actions">
            <div className="credit-chip" title="Available credits">
              <span>
                {DEMO_MODE
                  ? "Demo"
                  : profile
                    ? (profile.creditBalance?.toLocaleString() ?? "—")
                    : "—"}
              </span>
              <small>credits</small>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="Open notifications"
            >
              <Bell size={19} />
            </button>
            <button
              className="account-button"
              type="button"
              aria-label="Open account menu"
            >
              <span className="avatar" aria-hidden="true">
                {userInitials}
              </span>
              <span className="account-copy">
                <strong>{workspaceName ?? "Workspace"}</strong>
                <small>{userRole ?? "Member"}</small>
              </span>
              <CaretDown size={14} aria-hidden="true" />
            </button>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {children}
        </main>
        <nav className="mobile-app-nav" aria-label="Mobile navigation">
          {(
            [
              { href: "/home", label: "Overview", icon: House },
              { href: "/projects", label: "Projects", icon: FolderOpen },
              { href: "/activity", label: "Activity", icon: Pulse },
              { href: "/settings", label: "Account", icon: GearSix },
            ] as const
          ).map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                href={href}
                className={active ? "active" : undefined}
                aria-current={active ? "page" : undefined}
                key={href}
              >
                <Icon size={20} weight="regular" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
      {commandOpen && (
        <div
          className="command-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setCommandOpen(false);
          }}
        >
          <section
            className="command-palette"
            role="dialog"
            aria-modal="true"
            aria-label="Command menu"
          >
            <header>
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input
                type="search"
                autoFocus
                aria-label="Search commands"
                placeholder="Search projects, entities, or commands"
              />
              <button
                type="button"
                className="icon-button compact"
                aria-label="Close command menu"
                onClick={() => setCommandOpen(false)}
              >
                <X size={16} />
              </button>
            </header>
            <div>
              <span>Quick navigation</span>
              {(
                [
                  ["/quick-convert", "Upload documents", "U"],
                  ["/projects", "Open projects", "P"],
                  ["/knowledge-bases", "Search entities", "E"],
                  ["/review", "Open Review Studio", "R"],
                  ["/benchmarks", "Run benchmark", "B"],
                  ["/settings", "Workspace settings", "S"],
                  ["/", "Product site", "H"],
                ] as const
              ).map(([href, label, key]) => (
                <Link
                  href={href}
                  onClick={() => setCommandOpen(false)}
                  key={href}
                >
                  <span>{label}</span>
                  <kbd>{key}</kbd>
                </Link>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
