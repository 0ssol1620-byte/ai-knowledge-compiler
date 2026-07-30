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
  { href: "/home", label: "대시보드", icon: House },
  { href: "/projects", label: "프로젝트", icon: FolderOpen },
  { href: "/quick-convert", label: "빠른 변환", icon: Lightning },
  { href: "/knowledge-bases", label: "지식베이스", icon: TreeStructure },
  { href: "/benchmarks", label: "벤치마크", icon: Flask },
  { href: "/api-workflows", label: "API & 워크플로", icon: BracketsCurly },
] as const;

const secondaryNavigation = [
  { href: "/activity", label: "활동", icon: Pulse },
  { href: "/usage", label: "사용량", icon: CreditCard },
  { href: "/settings", label: "설정", icon: GearSix },
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
            : "세션 확인 중 알 수 없는 오류가 발생했습니다.",
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
            ? "로그인으로 이동 중입니다."
            : sessionState === "error"
              ? `세션을 확인하지 못했습니다: ${sessionError ?? "연결을 확인하세요."}`
              : "세션을 확인하고 있습니다."}
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
            다시 시도
          </button>
        )}
      </main>
    );
  }

  const workspaceName = DEMO_MODE
    ? "샘플 워크스페이스"
    : profile?.workspaceName;
  const userRole = DEMO_MODE ? "Demo" : profile?.roles[0];
  const userInitials = (DEMO_MODE ? "DE" : (profile?.displayName ?? "—"))
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className={clsx("app-frame", collapsed && "sidebar-collapsed")}>
      {DEMO_MODE && (
        <div className="demo-mode-banner" role="status">
          샘플 화면 · 실제 문서 처리와 크레딧 사용은 발생하지 않습니다.
        </div>
      )}
      <aside className="sidebar" aria-label="주 메뉴">
        <div className="sidebar-brand-row">
          <Link
            href="/"
            className="brand-link"
            aria-label="제품 사이트로 돌아가기"
          >
            <BrandMark compact={collapsed} />
          </Link>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
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
            <strong>외부 처리 보호</strong>
            <span>
              {DEMO_MODE
                ? "외부 API 꺼짐"
                : profile?.externalProcessingEnabled === true
                  ? "외부 처리 동의 활성"
                  : profile?.externalProcessingEnabled === false
                    ? "외부 API 꺼짐"
                    : "정책 확인 필요"}
            </span>
          </div>
        </div>

        <nav className="sidebar-secondary" aria-label="워크스페이스 관리">
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
            title={collapsed ? "오픈소스 고지" : undefined}
          >
            <Lifebuoy size={19} aria-hidden="true" />
            <span>도움말·고지</span>
          </Link>
          <Link
            href="/"
            className="nav-item product-site-nav"
            title={collapsed ? "제품 사이트" : undefined}
          >
            <ArrowLeft size={19} aria-hidden="true" />
            <span>제품 사이트</span>
          </Link>
        </nav>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-leading">
            <Link href="/" className="product-back-link">
              <ArrowLeft size={15} aria-hidden="true" />
              <span>제품 사이트</span>
            </Link>
            <button
              type="button"
              className="topbar-search"
              onClick={() => setCommandOpen(true)}
              aria-haspopup="dialog"
            >
              <MagnifyingGlass size={17} aria-hidden="true" />
              <span>프로젝트, 문서, 근거 검색</span>
              <kbd>Ctrl K</kbd>
            </button>
          </div>
          <div className="topbar-actions">
            <div className="credit-chip" title="사용 가능한 크레딧">
              <span>
                {DEMO_MODE
                  ? "샘플"
                  : profile
                    ? (profile.creditBalance?.toLocaleString() ?? "—")
                    : "—"}
              </span>
              <small>크레딧</small>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="알림 열기"
            >
              <Bell size={19} />
            </button>
            <button
              className="account-button"
              type="button"
              aria-label="계정 메뉴 열기"
            >
              <span className="avatar" aria-hidden="true">
                {userInitials}
              </span>
              <span className="account-copy">
                <strong>{workspaceName ?? "워크스페이스"}</strong>
                <small>{userRole ?? "Member"}</small>
              </span>
              <CaretDown size={14} aria-hidden="true" />
            </button>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {children}
        </main>
        <nav className="mobile-app-nav" aria-label="모바일 주 메뉴">
          {(
            [
              { href: "/home", label: "대시보드", icon: House },
              { href: "/projects", label: "프로젝트", icon: FolderOpen },
              { href: "/activity", label: "활동", icon: Pulse },
              { href: "/settings", label: "내 정보", icon: GearSix },
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
            aria-label="명령 팔레트"
          >
            <header>
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input
                type="search"
                autoFocus
                aria-label="명령 검색"
                placeholder="프로젝트, 엔터티 또는 명령 검색"
              />
              <button
                type="button"
                className="icon-button compact"
                aria-label="명령 팔레트 닫기"
                onClick={() => setCommandOpen(false)}
              >
                <X size={16} />
              </button>
            </header>
            <div>
              <span>빠른 이동</span>
              {(
                [
                  ["/quick-convert", "파일 업로드", "U"],
                  ["/projects", "프로젝트 열기", "P"],
                  ["/knowledge-bases", "엔터티 검색", "E"],
                  ["/review", "검토 스튜디오", "R"],
                  ["/benchmarks", "벤치마크 실행", "B"],
                  ["/settings", "워크스페이스 설정", "S"],
                  ["/", "제품 사이트", "H"],
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
