"use client";

import { Plus, X } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useId, useRef, useState } from "react";

import { createProject } from "@/lib/api-client";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function CreateProjectButton({
  variant = "primary",
  label,
}: {
  variant?: "primary" | "inline";
  label?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const titleId = useId();
  const queryClient = useQueryClient();
  const nameInputRef = useRef<HTMLInputElement>(null);
  const closeDialog = () => {
    if (!submitting) setOpen(false);
  };
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose: closeDialog,
    initialFocusRef: nameInputRef,
  });

  return (
    <>
      <button
        className={
          variant === "inline" ? "inline-create-button" : "primary-button"
        }
        type="button"
        onClick={() => {
          setError(undefined);
          setOpen(true);
        }}
      >
        {label ?? (
          <>
            <Plus size={17} weight="bold" aria-hidden="true" />새 프로젝트
          </>
        )}
      </button>
      {open && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <section
            ref={dialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
          >
            <div className="modal-heading">
              <div>
                <p className="eyebrow">New knowledge project</p>
                <h2 id={titleId}>프로젝트 만들기</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                disabled={submitting}
                onClick={closeDialog}
                aria-label="대화상자 닫기"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (DEMO_MODE) {
                  setError("Demo mode에서는 프로젝트를 저장하지 않습니다.");
                  return;
                }
                const form = new FormData(event.currentTarget);
                setSubmitting(true);
                setError(undefined);
                void createProject({
                  name: String(form.get("name") ?? ""),
                  description:
                    String(form.get("description") ?? "") || undefined,
                  mode: String(form.get("mode") ?? "balanced"),
                })
                  .then(() => {
                    void queryClient.invalidateQueries({
                      queryKey: ["dashboard"],
                    });
                    setOpen(false);
                  })
                  .catch((reason: unknown) => {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "프로젝트를 만들지 못했습니다.",
                    );
                  })
                  .finally(() => setSubmitting(false));
              }}
            >
              <label className="field">
                <span>프로젝트 이름</span>
                <input
                  ref={nameInputRef}
                  required
                  name="name"
                  maxLength={120}
                  placeholder="예: 제품 매뉴얼 지식베이스"
                />
              </label>
              <label className="field">
                <span>
                  설명 <small>선택</small>
                </span>
                <textarea
                  name="description"
                  rows={3}
                  maxLength={500}
                  placeholder="컴파일할 자료와 활용 목적"
                />
              </label>
              <fieldset className="mode-fieldset">
                <legend>기본 처리 모드</legend>
                {[
                  ["balanced", "Balanced", "품질과 비용의 균형", true],
                  ["precision", "Precision", "중요 문서 교차 검증", false],
                  ["private", "Private", "외부 모델 API 금지", false],
                ].map(([value, name, description, checked]) => (
                  <label className="mode-option" key={String(value)}>
                    <input
                      type="radio"
                      name="mode"
                      value={String(value)}
                      defaultChecked={Boolean(checked)}
                    />
                    <span>
                      <strong>{name}</strong>
                      <small>{description}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={submitting}
                  onClick={closeDialog}
                >
                  취소
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={submitting}
                >
                  {submitting ? "저장 중" : "프로젝트 만들기"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
