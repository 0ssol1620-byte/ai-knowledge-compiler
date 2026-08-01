"use client";

import {
  ArrowRight,
  BracketsCurly,
  CreditCard,
  FileText,
  Flask,
  FolderOpen,
  GearSix,
  House,
  Lightning,
  MagnifyingGlass,
  ShieldCheck,
  TreeStructure,
  X,
} from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { useStructaraLocale } from "@/components/locale-provider";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const commandDefinitions = [
  {
    href: "/app/home",
    shortcut: "H",
    icon: House,
    keywords: "dashboard activity overview 대시보드 활동 개요",
    en: {
      label: "Workspace home",
      description:
        "Open active jobs, integrity findings, and knowledge health.",
      category: "Navigate",
    },
    ko: {
      label: "워크스페이스 홈",
      description: "진행 중인 작업, 무결성 상태, 지식 상태를 확인합니다.",
      category: "이동",
    },
  },
  {
    href: "/intake",
    shortcut: "U",
    icon: Lightning,
    keywords: "new convert import files 새 문서 변환 업로드 가져오기",
    en: {
      label: "Intake a collection",
      description:
        "Preserve folder structure and prepare a private-first manifest.",
      category: "Create",
    },
    ko: {
      label: "컬렉션 수집",
      description: "폴더 구조를 보존하고 비공개 우선 매니페스트를 준비합니다.",
      category: "생성",
    },
  },
  {
    href: "/app/projects",
    shortcut: "P",
    icon: FolderOpen,
    keywords: "project list owner documents 프로젝트 목록 소유자 문서",
    en: {
      label: "Open projects",
      description: "Search, filter, and manage project boundaries.",
      category: "Navigate",
    },
    ko: {
      label: "프로젝트 열기",
      description: "프로젝트 경계를 검색하고 필터링하며 관리합니다.",
      category: "이동",
    },
  },
  {
    href: "/app/knowledge-bases",
    shortcut: "K",
    icon: TreeStructure,
    keywords: "notes relations graph evidence 지식 노트 관계 그래프 근거",
    en: {
      label: "Explore knowledge",
      description: "Inspect notes, relations, and adjacent source evidence.",
      category: "Navigate",
    },
    ko: {
      label: "지식 탐색",
      description: "노트, 관계, 인접 원문 근거를 확인합니다.",
      category: "이동",
    },
  },
  {
    href: "/integrity",
    shortcut: "I",
    icon: FileText,
    keywords: "integrity unresolved quarantine evidence 무결성 미해결 격리 근거",
    en: {
      label: "Open Integrity Console",
      description:
        "Inspect automatic repair, unresolved findings, quarantine, and durable evidence.",
      category: "Navigate",
    },
    ko: {
      label: "무결성 콘솔 열기",
      description: "자동 복구, 미해결 항목, 격리 상태와 불변 근거를 확인합니다.",
      category: "이동",
    },
  },
  {
    href: "/app/jobs",
    shortcut: "J",
    icon: Flask,
    keywords: "processing queue retry operation 처리 작업 큐 재시도 운영",
    en: {
      label: "Inspect jobs",
      description: "Inspect processing state, retries, and operational history.",
      category: "Operate",
    },
    ko: {
      label: "작업 확인",
      description: "처리 상태, 재시도, 운영 이력을 확인합니다.",
      category: "운영",
    },
  },
  {
    href: "/benchmarks",
    shortcut: "B",
    icon: Flask,
    keywords: "quality method results limitations 벤치마크 품질 방법 결과 한계",
    en: {
      label: "Open benchmark methodology",
      description:
        "Inspect available methodology, evidence status, and limitations.",
      category: "Measure",
    },
    ko: {
      label: "벤치마크 방법론 열기",
      description: "공개 가능한 방법론, 근거 상태, 한계를 확인합니다.",
      category: "측정",
    },
  },
  {
    href: "/app/api",
    shortcut: "A",
    icon: BracketsCurly,
    keywords: "developer endpoint key webhook 개발자 엔드포인트 키 웹훅",
    en: {
      label: "Open API Console",
      description: "Inspect API workflows, keys, and request contracts.",
      category: "Develop",
    },
    ko: {
      label: "API Console 열기",
      description: "API 워크플로, 키, 요청 계약을 확인합니다.",
      category: "개발",
    },
  },
  {
    href: "/app/usage",
    shortcut: "G",
    icon: CreditCard,
    keywords: "cost credits pages storage 사용량 비용 크레딧 페이지 저장소",
    en: {
      label: "Inspect usage",
      description: "Inspect pages, credits, storage, and operating profile.",
      category: "Operate",
    },
    ko: {
      label: "사용량 확인",
      description: "페이지, 크레딧, 저장소, 운영 프로필을 확인합니다.",
      category: "운영",
    },
  },
  {
    href: "/app/settings/security",
    shortcut: "S",
    icon: ShieldCheck,
    keywords: "policy identity retention audit 보안 정책 인증 보존 감사",
    en: {
      label: "Open Security Center",
      description:
        "Inspect policy status, identity, retention, and audit controls.",
      category: "Govern",
    },
    ko: {
      label: "Security Center 열기",
      description: "정책 상태, 인증, 보존, 감사 제어를 확인합니다.",
      category: "거버넌스",
    },
  },
  {
    href: "/settings",
    shortcut: ",",
    icon: GearSix,
    keywords: "preferences organization configuration 설정 환경설정 조직 구성",
    en: {
      label: "Workspace settings",
      description: "Configure workspace preferences and connected policies.",
      category: "Govern",
    },
    ko: {
      label: "워크스페이스 설정",
      description: "워크스페이스 환경설정과 연결 정책을 구성합니다.",
      category: "거버넌스",
    },
  },
] as const;

const paletteCopy = {
  en: {
    dialog: "Workspace command menu",
    search: "Search workspace commands",
    placeholder: "Navigate projects, integrity, knowledge, or settings",
    clearSearch: "Clear command search",
    clear: "Clear",
    close: "Close command menu",
    command: "command",
    commands: "commands",
    keyboard: "↑↓ move · Enter open · Esc close",
    noMatch: "No matching command",
    noMatchBody:
      "Search the navigation and operating commands currently available in this workspace.",
  },
  ko: {
    dialog: "워크스페이스 명령 메뉴",
    search: "워크스페이스 명령 검색",
    placeholder: "프로젝트, 무결성, 지식 또는 설정으로 이동",
    clearSearch: "명령 검색어 지우기",
    clear: "지우기",
    close: "명령 메뉴 닫기",
    command: "개 명령",
    commands: "개 명령",
    keyboard: "↑↓ 이동 · Enter 열기 · Esc 닫기",
    noMatch: "일치하는 명령 없음",
    noMatchBody:
      "현재 워크스페이스에서 사용할 수 있는 이동 및 운영 명령을 검색하세요.",
  },
} as const;

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { locale } = useStructaraLocale();
  const copy = locale === "ko" ? paletteCopy.ko : paletteCopy.en;
  const commands = useMemo(
    () =>
      commandDefinitions.map((definition) => ({
        ...definition,
        ...(locale === "ko" ? definition.ko : definition.en),
      })),
    [locale],
  );
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose,
    initialFocusRef: inputRef,
  });
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(() => {
    const normalized = query
      .trim()
      .toLocaleLowerCase(locale === "ko" ? "ko-KR" : "en-US");
    if (!normalized) return commands;
    return commands.filter((command) =>
      `${command.label} ${command.description} ${command.category} ${command.keywords}`
        .toLocaleLowerCase(locale === "ko" ? "ko-KR" : "en-US")
        .includes(normalized),
    );
  }, [commands, locale, query]);
  const safeActiveIndex =
    filtered.length === 0 ? -1 : Math.min(activeIndex, filtered.length - 1);
  const active = safeActiveIndex >= 0 ? filtered[safeActiveIndex] : undefined;

  function navigate(href: string) {
    router.push(href as never);
    onClose();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) =>
        filtered.length === 0
          ? 0
          : (Math.min(current, filtered.length - 1) + 1) % filtered.length,
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) =>
        filtered.length === 0
          ? 0
          : (Math.min(current, filtered.length - 1) - 1 + filtered.length) %
            filtered.length,
      );
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(0, filtered.length - 1));
      return;
    }
    if (event.key === "Enter" && active) {
      event.preventDefault();
      navigate(active.href);
    }
  }

  if (!open) return null;

  return (
    <div
      className="command-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="command-palette command-palette-premium"
        role="dialog"
        aria-modal="true"
        aria-label={copy.dialog}
        tabIndex={-1}
      >
        <header>
          <MagnifyingGlass size={18} aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            role="combobox"
            aria-label={copy.search}
            aria-expanded="true"
            aria-controls="command-results"
            aria-activedescendant={
              active ? `command-option-${safeActiveIndex}` : undefined
            }
            autoComplete="off"
            value={query}
            placeholder={copy.placeholder}
            onChange={(event) => {
              setQuery(event.currentTarget.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
          />
          {query ? (
            <button
              type="button"
              className="command-clear-button"
              aria-label={copy.clearSearch}
              onClick={() => {
                setQuery("");
                setActiveIndex(0);
                inputRef.current?.focus();
              }}
            >
              {copy.clear}
            </button>
          ) : (
            <kbd>⌘ K</kbd>
          )}
          <button
            type="button"
            className="icon-button compact"
            aria-label={copy.close}
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>

        <div className="command-result-meta" aria-live="polite">
          <span>
            {filtered.length}{" "}
            {filtered.length === 1 ? copy.command : copy.commands}
          </span>
          <small>{copy.keyboard}</small>
        </div>

        <div
          id="command-results"
          className="command-result-list"
          role="listbox"
        >
          {filtered.length === 0 ? (
            <div className="command-empty-state">
              <MagnifyingGlass size={24} aria-hidden="true" />
              <strong>{copy.noMatch}</strong>
              <p>{copy.noMatchBody}</p>
            </div>
          ) : (
            filtered.map((command, index) => {
              const Icon = command.icon;
              return (
                <button
                  type="button"
                  id={`command-option-${index}`}
                  role="option"
                  aria-selected={index === safeActiveIndex}
                  data-active={index === safeActiveIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => navigate(command.href)}
                  key={command.href}
                >
                  <span className="command-option-icon">
                    <Icon size={17} aria-hidden="true" />
                  </span>
                  <span className="command-option-copy">
                    <strong>{command.label}</strong>
                    <small>{command.description}</small>
                  </span>
                  <span className="command-option-meta">
                    <i>{command.category}</i>
                    <kbd>{command.shortcut}</kbd>
                  </span>
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
