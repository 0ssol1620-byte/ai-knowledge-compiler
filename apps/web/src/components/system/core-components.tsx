import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import styles from "./core-components.module.css";

export type CoreDensity = "compact" | "comfortable";
export type CoreStoryState = "default" | "hover" | "focus";

export function CoreButton({
  busy = false,
  children,
  density = "comfortable",
  storyState = "default",
  tone = "primary",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  density?: CoreDensity;
  storyState?: CoreStoryState;
  tone?: "primary" | "secondary" | "quiet";
}) {
  return (
    <button
      {...props}
      type={props.type ?? "button"}
      className={styles.button}
      data-density={density}
      data-story-state={storyState}
      data-tone={tone}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
    >
      {busy ? <span className={styles.spinner} aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

export function StatusBadge({
  status,
  children,
}: {
  status: "verified" | "processing" | "warning" | "unresolved" | "quarantined";
  children: ReactNode;
}) {
  return (
    <span className={styles.badge} data-kind="status" data-tone={status}>
      {children}
    </span>
  );
}

export function OriginBadge({ children }: { children: ReactNode }) {
  return (
    <span className={styles.badge} data-kind="origin">
      {children}
    </span>
  );
}

export function CoreSurface({
  density = "comfortable",
  children,
  ...props
}: HTMLAttributes<HTMLElement> & {
  density?: CoreDensity;
}) {
  return (
    <section {...props} className={styles.surface} data-density={density}>
      {children}
    </section>
  );
}

export function SystemState({
  action,
  body,
  state,
  title,
}: {
  action?: ReactNode;
  body: string;
  state: "loading" | "empty" | "error";
  title: string;
}) {
  return (
    <section
      className={styles.statePanel}
      data-state={state}
      aria-live={state === "loading" ? "polite" : undefined}
      role={state === "error" ? "alert" : "status"}
    >
      <StatusBadge status={state === "error" ? "unresolved" : "processing"}>
        {state}
      </StatusBadge>
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </section>
  );
}

export function CoreComponentShowcase({
  density = "comfortable",
  locale = "en",
  motion = "full",
  state = "default",
}: {
  density?: CoreDensity;
  locale?: "en" | "ko";
  motion?: "full" | "reduced";
  state?: CoreStoryState | "loading" | "empty" | "error";
}) {
  const copy =
    locale === "ko"
      ? {
          title: "근거가 연결된 지식 패키지",
          body: "출처 좌표, 수치 권위, 검증 상태를 잃지 않고 긴 한글 문서 컬렉션을 배포 가능한 구조로 컴파일합니다.",
          action: "컬렉션 처리 시작",
        }
      : {
          title: "An evidence-linked knowledge package",
          body: "Compile a long English document collection into a deployable structure without losing source coordinates, numeric authority, or verification state.",
          action: "Start collection processing",
        };
  if (state === "loading" || state === "empty" || state === "error") {
    const stateCopy: Record<
      "loading" | "empty" | "error",
      readonly [string, string]
    > =
      locale === "ko"
        ? {
            loading: [
              "검증된 구조를 컴파일하는 중",
              "서명된 처리 이벤트만 진행 상태를 갱신합니다.",
            ],
            empty: [
              "선택한 컬렉션이 없습니다",
              "안전한 원본 컬렉션을 선택해 시작하세요.",
            ],
            error: [
              "처리가 안전하게 중단됐습니다",
              "원본은 변경되지 않았습니다. 보고된 경계를 해결한 뒤 다시 시도하세요.",
            ],
          }
        : {
            loading: [
              "Compiling verified structure",
              "Progress is driven by signed processing events.",
            ],
            empty: [
              "No collection selected",
              "Choose a safe source collection to begin.",
            ],
            error: [
              "Processing stopped safely",
              "The source remains unchanged. Retry after resolving the reported boundary.",
            ],
          };
    return (
      <div
        className={motion === "reduced" ? styles.reducedMotion : undefined}
        lang={locale === "ko" ? "ko" : "en"}
      >
        <SystemState
          state={state}
          title={stateCopy[state][0]}
          body={stateCopy[state][1]}
          action={
            state === "error" ? (
              <CoreButton tone="secondary">
                {locale === "ko" ? "안전하게 다시 시도" : "Retry safely"}
              </CoreButton>
            ) : undefined
          }
        />
      </div>
    );
  }
  return (
    <div
      className={`${styles.stack} ${motion === "reduced" ? styles.reducedMotion : ""}`}
      lang={locale === "ko" ? "ko" : "en"}
    >
      <CoreSurface density={density}>
        <div className={styles.row}>
          <StatusBadge status="verified">Verified</StatusBadge>
          <StatusBadge status="warning">Warning</StatusBadge>
          <StatusBadge status="unresolved">Unresolved</StatusBadge>
          <OriginBadge>Authority source</OriginBadge>
        </div>
        <h3>{copy.title}</h3>
        <p>{copy.body}</p>
        <div className={styles.row}>
          <CoreButton density={density} storyState={state}>
            {copy.action}
          </CoreButton>
          <CoreButton density={density} tone="secondary">
            Inspect evidence
          </CoreButton>
          <CoreButton density={density} tone="quiet">
            View integrity
          </CoreButton>
        </div>
      </CoreSurface>
    </div>
  );
}

export const coreComponentStyles = {
  mobileFrame: styles.mobileFrame,
};
