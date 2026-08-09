"use client";

import {
  CheckCircle,
  Clock,
  FunnelSimple,
  MagnifyingGlass,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import clsx from "clsx";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";

import { publicRouteLabel } from "@/lib/public-processing-labels";
import type { PageStatus, PageSummary } from "@/lib/types";

const statusIcon = {
  verified: CheckCircle,
  warning: WarningCircle,
  review: WarningCircle,
  failed: XCircle,
} as const;

const pageStatuses: PageStatus[] = [
  "uploaded",
  "security_scanning",
  "security_verified",
  "preflighting",
  "preflighted",
  "native_extracting",
  "ocr_queued",
  "ocr_running",
  "normalizing",
  "validating",
  "completed",
  "needs_review",
  "retry_scheduled",
  "failed",
];

type QualityFilter = PageSummary["quality_state"] | "all";
type StatusFilter = PageStatus | "all";

export function PageRail({
  pages,
  selectedPageId,
  onSelect,
}: {
  pages: PageSummary[];
  selectedPageId: string;
  onSelect: (pageId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [qualityFilter, setQualityFilter] = useState<QualityFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const [rovingPageId, setRovingPageId] = useState<string | undefined>(
    selectedPageId,
  );
  const railRef = useRef<HTMLElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const previousLocationRef = useRef({
    query,
    qualityFilter,
    selectedPageId,
    statusFilter,
  });
  const filterPanelId = useId();
  const resultCountId = useId();

  const filteredPages = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return pages.filter((page) => {
      if (qualityFilter !== "all" && page.quality_state !== qualityFilter) {
        return false;
      }
      if (statusFilter !== "all" && page.status !== statusFilter) {
        return false;
      }
      if (!normalizedQuery) return true;
      const searchable = [
        `page ${page.page_number}`,
        String(page.page_number),
        statusLabel(page.status),
        qualityLabel(page.quality_state),
        publicRouteLabel(page.route_label),
        publicRouteLabel(page.route_profile),
      ]
        .join(" ")
        .toLocaleLowerCase();
      return searchable.includes(normalizedQuery);
    });
  }, [pages, qualityFilter, query, statusFilter]);
  const effectiveRovingPageId =
    filteredPages.find((page) => page.id === rovingPageId)?.id ??
    filteredPages.find((page) => page.id === selectedPageId)?.id ??
    filteredPages[0]?.id;
  const initialSelectedIndex = Math.max(
    0,
    filteredPages.findIndex((page) => page.id === selectedPageId),
  );

  useEffect(() => {
    const previous = previousLocationRef.current;
    const locationChanged =
      previous.query !== query ||
      previous.qualityFilter !== qualityFilter ||
      previous.selectedPageId !== selectedPageId ||
      previous.statusFilter !== statusFilter;
    previousLocationRef.current = {
      query,
      qualityFilter,
      selectedPageId,
      statusFilter,
    };
    if (!locationChanged) return;

    const selectedIndex = filteredPages.findIndex(
      (page) => page.id === selectedPageId,
    );
    if (selectedIndex < 0) return;
    const frame = window.requestAnimationFrame(() => {
      virtuosoRef.current?.scrollToIndex({
        index: selectedIndex,
        align: "center",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [filteredPages, qualityFilter, query, selectedPageId, statusFilter]);

  function focusRenderedPage(pageId: string, attempt = 0) {
    window.requestAnimationFrame(() => {
      const target = Array.from(
        railRef.current?.querySelectorAll<HTMLButtonElement>(
          "[data-page-id]",
        ) ?? [],
      ).find((button) => button.dataset.pageId === pageId);
      if (target) {
        target.focus();
      } else if (attempt < 2) {
        focusRenderedPage(pageId, attempt + 1);
      }
    });
  }

  function moveFocus(
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) {
    let nextIndex: number | undefined;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      nextIndex = Math.min(filteredPages.length - 1, currentIndex + 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      nextIndex = Math.max(0, currentIndex - 1);
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = filteredPages.length - 1;
    }
    if (nextIndex === undefined || nextIndex === currentIndex) return;

    event.preventDefault();
    const nextPage = filteredPages[nextIndex];
    if (!nextPage) return;
    setRovingPageId(nextPage.id);
    virtuosoRef.current?.scrollToIndex({
      index: nextIndex,
      align: "center",
    });
    focusRenderedPage(nextPage.id);
  }

  const activeFilterCount =
    Number(qualityFilter !== "all") + Number(statusFilter !== "all");

  return (
    <section
      ref={railRef}
      className="workspace-panel page-rail"
      aria-label="Page navigation"
    >
      <header className="workspace-panel-header compact">
        <div>
          <strong>Pages</strong>
          <span>{pages.length} pages</span>
        </div>
        <button
          ref={filterButtonRef}
          className={clsx(
            "icon-button compact",
            activeFilterCount > 0 && "filter-active",
          )}
          type="button"
          aria-label={`Page filters${
            activeFilterCount ? `, ${activeFilterCount} applied` : ""
          }`}
          aria-expanded={filterOpen}
          aria-controls={filterPanelId}
          onClick={() => setFilterOpen((open) => !open)}
        >
          <FunnelSimple size={15} aria-hidden="true" />
        </button>
      </header>
      <div className="rail-search">
        <MagnifyingGlass size={14} aria-hidden="true" />
        <input
          type="search"
          aria-label="Search pages"
          aria-describedby={resultCountId}
          placeholder="Search page, status, or route"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
      </div>
      {filterOpen && (
        <div
          className="page-filter-panel"
          id={filterPanelId}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            setFilterOpen(false);
            filterButtonRef.current?.focus();
          }}
        >
          <label>
            <span>Quality</span>
            <select
              aria-label="Quality filter"
              value={qualityFilter}
              onChange={(event) =>
                setQualityFilter(event.currentTarget.value as QualityFilter)
              }
            >
              <option value="all">All quality states</option>
              <option value="verified">Verified</option>
              <option value="warning">Warning</option>
              <option value="review">Unresolved</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label>
            <span>Status</span>
            <select
              aria-label="Processing status filter"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.currentTarget.value as StatusFilter)
              }
            >
              <option value="all">All statuses</option>
              {pageStatuses.map((status) => (
                <option key={status} value={status}>
                  {statusLabel(status)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary-button compact"
            disabled={activeFilterCount === 0}
            onClick={() => {
              setQualityFilter("all");
              setStatusFilter("all");
            }}
          >
            Reset filters
          </button>
        </div>
      )}
      <p className="page-result-count" id={resultCountId}>
        {filteredPages.length} / {pages.length} pages
      </p>
      <div
        className="page-virtual-list"
        role="navigation"
        aria-label="Filtered pages"
      >
        {filteredPages.length > 0 ? (
          <Virtuoso
            ref={virtuosoRef}
            data={filteredPages}
            initialTopMostItemIndex={{
              align: "center",
              index: initialSelectedIndex,
            }}
            overscan={280}
            itemContent={(index, page) => {
              const StatusIcon = statusIcon[page.quality_state];
              const active = page.id === selectedPageId;
              const running = [
                "ocr_running",
                "native_extracting",
                "normalizing",
              ].includes(page.status);
              return (
                <button
                  type="button"
                  data-page-id={page.id}
                  className={clsx("page-card", active && "active")}
                  onClick={() => {
                    setRovingPageId(page.id);
                    onSelect(page.id);
                  }}
                  onFocus={() => setRovingPageId(page.id)}
                  onKeyDown={(event) => moveFocus(event, index)}
                  tabIndex={page.id === effectiveRovingPageId ? 0 : -1}
                  aria-current={active ? "page" : undefined}
                  aria-label={`Page ${page.page_number}, ${qualityLabel(
                    page.quality_state,
                  )}, ${statusLabel(page.status)}, ${publicRouteLabel(page.route_label)}`}
                >
                  <span
                    className={clsx(
                      "page-thumbnail",
                      running && "is-processing",
                    )}
                    aria-hidden="true"
                  >
                    <span className="thumb-line wide" />
                    <span className="thumb-line" />
                    <span className="thumb-line medium" />
                    <span className="thumb-table">
                      <i />
                      <i />
                      <i />
                      <i />
                    </span>
                  </span>
                  <span className="page-card-copy">
                    <span>
                      <strong>Page {page.page_number}</strong>
                      <StatusIcon
                        size={14}
                        weight="fill"
                        className={`quality-${page.quality_state}`}
                        aria-hidden="true"
                      />
                    </span>
                    <small>{statusLabel(page.status)}</small>
                    <span
                      className={clsx(
                        "route-badge",
                        publicRouteLabel(page.route_label).toLowerCase(),
                      )}
                    >
                      {publicRouteLabel(page.route_label)}
                    </span>
                  </span>
                  {running && (
                    <Clock
                      className="running-clock"
                      size={14}
                      aria-hidden="true"
                    />
                  )}
                </button>
              );
            }}
          />
        ) : (
          <div className="page-filter-empty">
            <p>No pages match these conditions.</p>
            <button
              type="button"
              className="secondary-button compact"
              onClick={() => {
                setQuery("");
                setQualityFilter("all");
                setStatusFilter("all");
              }}
            >
              Clear search and filters
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function statusLabel(status: PageSummary["status"]): string {
  const labels: Record<PageSummary["status"], string> = {
    uploaded: "Uploaded",
    security_scanning: "Security scan",
    security_verified: "Security verified",
    preflighting: "Preflight analysis",
    preflighted: "Preflight complete",
    native_extracting: "Native extraction",
    ocr_queued: "OCR queued",
    ocr_running: "Visual recognition",
    normalizing: "Restoring structure",
    validating: "Validating result",
    completed: "Verified",
    needs_review: "Unresolved",
    retry_scheduled: "Retry scheduled",
    failed: "Processing failed",
  };
  return labels[status];
}

function qualityLabel(state: PageSummary["quality_state"]): string {
  return {
    verified: "Verified",
    warning: "Warning",
    review: "Unresolved",
    failed: "Failed",
  }[state];
}
