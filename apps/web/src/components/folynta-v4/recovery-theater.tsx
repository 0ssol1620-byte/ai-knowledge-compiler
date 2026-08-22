"use client";

import {
  ArrowRight,
  CheckCircle,
  Crosshair,
  Warning,
  Wrench,
} from "@phosphor-icons/react";
import { useState } from "react";

import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

type RecoveryState = "detected" | "recovered" | "verified";

export function RecoveryTheater({ locale }: { locale: StructaraLocale }) {
  const [state, setState] = useState<RecoveryState>("detected");
  const [technical, setTechnical] = useState(false);
  const ko = locale === "ko";
  const next = state === "detected" ? "recovered" : "verified";
  return (
    <section
      className={`${styles.section} ${styles.darkSection}`}
      data-scene="03-recovery"
    >
      <header className={styles.sectionHeading}>
        <p>03 · RECOVERY THEATER</p>
        <h2>
          {ko
            ? "누락을 숨기지 않고, 가장 작은 범위만 다시 처리합니다."
            : "Missing content stays visible. Only the smallest affected scope is retried."}
        </h2>
        <span>
          {ko
            ? "고정 공개 공시 픽스처로 복구 상태를 직접 전환해 보세요. 시간 기반 가짜 진행률은 없습니다."
            : "Step through recovery states on a fixed public filing fixture. There is no time-based fake progress."}
        </span>
      </header>
      <div className={styles.recoveryFrame} data-state={state}>
        <div className={styles.recoverySource}>
          <header>
            <span>JTC 2026 Q1 · PAGE 30</span>
            <b>{state.toUpperCase()}</b>
          </header>
          <div className={styles.recoveryTable}>
            <span>Revenue</span>
            <strong>4,902,490,901</strong>
            <span>Cost of sales</span>
            <strong>915,603,778</strong>
            <span>Gross profit</span>
            <strong className={styles.recoveryCell}>
              {state === "detected" ? "missing" : "3,986,887,123"}
            </strong>
          </div>
          <div className={styles.regionBox}>
            <Crosshair size={15} />
            <span>table.row[2] · bbox retained</span>
          </div>
        </div>
        <div className={styles.recoveryInspector}>
          <div
            className={styles.viewSwitch}
            role="group"
            aria-label={ko ? "복구 보기" : "Recovery view"}
          >
            <button
              type="button"
              aria-pressed={!technical}
              onClick={() => setTechnical(false)}
            >
              Basic
            </button>
            <button
              type="button"
              aria-pressed={technical}
              onClick={() => setTechnical(true)}
            >
              Technical
            </button>
          </div>
          <div className={styles.stateRail}>
            {(["detected", "recovered", "verified"] as const).map(
              (item, index) => (
                <div
                  key={item}
                  data-active={state === item}
                  data-complete={
                    (["detected", "recovered", "verified"] as const).indexOf(
                      state,
                    ) >= index
                  }
                >
                  <i>{index + 1}</i>
                  <span>{item}</span>
                </div>
              ),
            )}
          </div>
          {technical ? (
            <dl className={styles.technicalList}>
              <div>
                <dt>Failure</dt>
                <dd>T01 · table shape</dd>
              </div>
              <div>
                <dt>Scope</dt>
                <dd>row · page 30</dd>
              </div>
              <div>
                <dt>Recipe</dt>
                <dd>cell_geometry_specialist</dd>
              </div>
              <div>
                <dt>Acceptance</dt>
                <dd>source + numeric conservation</dd>
              </div>
            </dl>
          ) : (
            <p>
              {state === "detected"
                ? ko
                  ? "표의 행 수와 원문 숫자 보존 검사가 누락을 발견했습니다."
                  : "Table shape and source-number conservation detected the omission."
                : state === "recovered"
                  ? ko
                    ? "문서 전체가 아니라 누락된 행만 재처리했습니다."
                    : "Only the missing row was reprocessed, not the full document."
                  : ko
                    ? "복구 결과가 원문 숫자와 독립 검증을 모두 통과했습니다."
                    : "The recovered row passed source-number and independent checks."}
            </p>
          )}
          {state !== "verified" ? (
            <button
              className={styles.recoveryAction}
              type="button"
              onClick={() => setState(next)}
            >
              {state === "detected" ? (
                <Wrench size={15} />
              ) : (
                <CheckCircle size={15} />
              )}
              {state === "detected"
                ? ko
                  ? "누락 행 복구"
                  : "Recover missing row"
                : ko
                  ? "원문으로 검증"
                  : "Verify against source"}
              <ArrowRight size={14} />
            </button>
          ) : (
            <a className={styles.recoveryAction} href="#actual-source">
              <CheckCircle size={15} />
              {ko ? "실제 원문에서 확인" : "Inspect actual source"}
              <ArrowRight size={14} />
            </a>
          )}
          <button
            className={styles.resetAction}
            type="button"
            onClick={() => setState("detected")}
          >
            <Warning size={13} />
            {ko ? "상태 초기화" : "Reset fixture"}
          </button>
        </div>
      </div>
    </section>
  );
}
