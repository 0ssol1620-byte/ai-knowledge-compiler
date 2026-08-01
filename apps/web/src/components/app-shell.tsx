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
} from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { CommandPalette } from "@/components/command-palette";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { useStructaraLocale } from "@/components/locale-provider";
import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { formatLocaleNumber } from "@/lib/locale";
import { normalizeSessionResponse, type SessionProfile } from "@/lib/session";

const navigation = [
  { href: "/app/home", key: "home", icon: House },
  { href: "/app/projects", key: "projects", icon: FolderOpen },
  { href: "/intake", key: "documents", icon: Lightning },
  { href: "/app/knowledge-bases", key: "knowledge", icon: TreeStructure },
  { href: "/app/jobs", key: "jobs", icon: Pulse },
  { href: "/app/exports", key: "exports", icon: Flask },
] as const;

const secondaryNavigation = [
  { href: "/app/api", key: "api", icon: BracketsCurly },
  { href: "/app/usage", key: "usage", icon: CreditCard },
  { href: "/app/settings/security", key: "security", icon: ShieldCheck },
  { href: "/settings", key: "settings", icon: GearSix },
] as const;

const shellCopy = {
  en: {
    home: "Home",
    projects: "Projects",
    documents: "Documents",
    knowledge: "Knowledge",
    jobs: "Jobs",
    exports: "Exports",
    api: "API",
    usage: "Usage",
    security: "Security",
    settings: "Settings",
    unknownSessionError:
      "An unknown error occurred while checking your session.",
    redirecting: "Redirecting to sign in.",
    sessionFailed: "We could not verify your session",
    checkConnection: "Check your connection.",
    checking: "Checking your session.",
    retry: "Try again",
    sampleWorkspace: "Sample workspace",
    demoRole: "Demo",
    demoBanner:
      "Demo workspace · No documents are processed and no credits are used.",
    primaryNav: "Primary navigation",
    productSiteReturn: "Return to product site",
    expandSidebar: "Expand sidebar",
    collapseSidebar: "Collapse sidebar",
    externalProcessing: "External processing",
    externalDisabled: "External providers disabled",
    consentEnabled: "Explicit consent enabled",
    policyReview: "Policy acknowledgment required",
    administration: "Workspace administration",
    help: "Help & notices",
    productSite: "Product site",
    search: "Search projects, documents, or evidence",
    availableCredits: "Available credits",
    demo: "Demo",
    credits: "credits",
    notifications: "Open notifications",
    accountSettings: "Open account settings",
    workspace: "Workspace",
    member: "Member",
    mobileNav: "Mobile navigation",
    overview: "Overview",
    activity: "Activity",
    account: "Account",
  },
  ko: {
    home: "홈",
    projects: "프로젝트",
    documents: "문서",
    knowledge: "지식",
    jobs: "작업",
    exports: "내보내기",
    api: "API",
    usage: "사용량",
    security: "보안",
    settings: "설정",
    unknownSessionError: "세션을 확인하는 중 알 수 없는 오류가 발생했습니다.",
    redirecting: "로그인 화면으로 이동합니다.",
    sessionFailed: "세션을 확인할 수 없습니다",
    checkConnection: "네트워크 연결을 확인하세요.",
    checking: "세션을 확인하고 있습니다.",
    retry: "다시 시도",
    sampleWorkspace: "샘플 워크스페이스",
    demoRole: "데모",
    demoBanner:
      "데모 워크스페이스 · 문서를 처리하지 않으며 크레딧도 사용하지 않습니다.",
    primaryNav: "주요 내비게이션",
    productSiteReturn: "제품 사이트로 돌아가기",
    expandSidebar: "사이드바 펼치기",
    collapseSidebar: "사이드바 접기",
    externalProcessing: "외부 처리",
    externalDisabled: "외부 제공업체 비활성화",
    consentEnabled: "명시적 동의 활성화",
    policyReview: "정책 확인 필요",
    administration: "워크스페이스 관리",
    help: "도움말 및 공지",
    productSite: "제품 사이트",
    search: "프로젝트, 문서 또는 근거 검색",
    availableCredits: "사용 가능 크레딧",
    demo: "데모",
    credits: "크레딧",
    notifications: "알림 열기",
    accountSettings: "계정 설정 열기",
    workspace: "워크스페이스",
    member: "구성원",
    mobileNav: "모바일 내비게이션",
    overview: "개요",
    activity: "활동",
    account: "계정",
  },
} as const;

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function AppShell({ children }: { children: ReactNode }) {
  const { locale } = useStructaraLocale();
  const copy = locale === "ko" ? shellCopy.ko : shellCopy.en;
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

  const marketingRoute =
    pathname === "/" ||
    [
      "/product",
      "/solutions",
      "/demo",
      "/film",
      "/research",
      "/security",
      "/pricing",
      "/customers",
      "/developers",
      "/company",
      "/legal",
    ].some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    ) ||
    pathname === "/benchmarks";
  const authRoute =
    pathname === "/login" ||
    pathname === "/signup" ||
    pathname === "/onboarding" ||
    pathname.startsWith("/forgot-password") ||
    pathname.startsWith("/sso");
  const publicRoute =
    marketingRoute ||
    authRoute ||
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
          reason instanceof Error ? reason.message : copy.unknownSessionError,
        );
        setSessionState("error");
      });
    return () => controller.abort();
  }, [
    copy.unknownSessionError,
    pathname,
    publicRoute,
    router,
    sessionAttempt,
    setSession,
  ]);

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

  if (authRoute || pathname === "/verify-email") {
    return children;
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
            ? copy.redirecting
            : sessionState === "error"
              ? `${copy.sessionFailed}: ${sessionError ?? copy.checkConnection}`
              : copy.checking}
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
            {copy.retry}
          </button>
        )}
      </main>
    );
  }

  const workspaceName = DEMO_MODE
    ? copy.sampleWorkspace
    : profile?.workspaceName;
  const userRole = DEMO_MODE ? copy.demoRole : profile?.roles[0];
  const userInitials = (DEMO_MODE ? "DE" : (profile?.displayName ?? "—"))
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className={clsx("app-frame", collapsed && "sidebar-collapsed")}>
      {DEMO_MODE && (
        <div className="demo-mode-banner" role="status">
          {copy.demoBanner}
        </div>
      )}
      <aside className="sidebar" aria-label={copy.primaryNav}>
        <div className="sidebar-brand-row">
          <Link
            href="/"
            className="brand-link"
            aria-label={copy.productSiteReturn}
          >
            <BrandMark compact={collapsed} />
          </Link>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={collapsed ? copy.expandSidebar : copy.collapseSidebar}
            onClick={() => setCollapsed((value) => !value)}
          >
            <SidebarSimple size={18} weight="regular" />
          </button>
        </div>

        <nav className="sidebar-nav">
          {navigation.map(({ href, key, icon: Icon }) => {
            const label = copy[key];
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
            <strong>{copy.externalProcessing}</strong>
            <span>
              {DEMO_MODE
                ? copy.externalDisabled
                : profile?.externalProcessingEnabled === true
                  ? copy.consentEnabled
                  : profile?.externalProcessingEnabled === false
                    ? copy.externalDisabled
                    : copy.policyReview}
            </span>
          </div>
        </div>

        <nav className="sidebar-secondary" aria-label={copy.administration}>
          {secondaryNavigation.map(({ href, key, icon: Icon }) => {
            const label = copy[key];
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
            title={collapsed ? copy.help : undefined}
          >
            <Lifebuoy size={19} aria-hidden="true" />
            <span>{copy.help}</span>
          </Link>
          <Link
            href="/"
            className="nav-item product-site-nav"
            title={collapsed ? copy.productSite : undefined}
          >
            <ArrowLeft size={19} aria-hidden="true" />
            <span>{copy.productSite}</span>
          </Link>
        </nav>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-leading">
            <Link
              href="/"
              className="product-back-link"
              aria-label={copy.productSite}
            >
              <ArrowLeft size={15} aria-hidden="true" />
              <span>{copy.productSite}</span>
            </Link>
            <button
              type="button"
              className="topbar-search"
              onClick={() => setCommandOpen(true)}
              aria-haspopup="dialog"
              aria-label={copy.search}
            >
              <MagnifyingGlass size={17} aria-hidden="true" />
              <span>{copy.search}</span>
              <kbd>Ctrl K</kbd>
            </button>
          </div>
          <div className="topbar-actions">
            <LocaleSwitcher compact className="app-locale-switcher" />
            <div className="credit-chip" title={copy.availableCredits}>
              <span>
                {DEMO_MODE
                  ? copy.demo
                  : profile
                    ? profile.creditBalance === undefined
                      ? "—"
                      : formatLocaleNumber(locale, profile.creditBalance)
                    : "—"}
              </span>
              <small>{copy.credits}</small>
            </div>
            <Link
              className="icon-button"
              href="/notices"
              aria-label={copy.notifications}
              data-shell-action="notifications"
            >
              <Bell size={19} />
            </Link>
            <Link
              className="account-button"
              href="/settings"
              aria-label={copy.accountSettings}
              data-shell-action="account"
            >
              <span className="avatar" aria-hidden="true">
                {userInitials}
              </span>
              <span className="account-copy">
                <strong>{workspaceName ?? copy.workspace}</strong>
                <small>{userRole ?? copy.member}</small>
              </span>
              <CaretDown size={14} aria-hidden="true" />
            </Link>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {children}
        </main>
        <nav className="mobile-app-nav" aria-label={copy.mobileNav}>
          {(
            [
              { href: "/home", label: copy.overview, icon: House },
              { href: "/projects", label: copy.projects, icon: FolderOpen },
              { href: "/activity", label: copy.activity, icon: Pulse },
              { href: "/settings", label: copy.account, icon: GearSix },
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
      <CommandPalette
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
      />
    </div>
  );
}
