"use client";

import { CheckCircle, LockKey, Warning } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import {
  createCollectionIntegrityDecision,
  INTEGRITY_REASON_BY_ACTION,
  type CollectionIntegrityDecision,
  type CollectionIntegrityDecisionAction,
  type CollectionIntegrityEvidenceReference,
  type CollectionIntegrityFinding,
} from "@/lib/collection-integrity-client";
import type { StructaraLocale } from "@/lib/locale";

type EvidenceKind = CollectionIntegrityEvidenceReference["kind"] | "none";

const COPY = {
  en: {
    title: "Optional customer decision",
    intro:
      "The autonomous pipeline is already complete or safely isolated. Use this only when a structured source reference supports a customer choice.",
    decision: "Decision",
    reason: "Audited reason code",
    evidenceKind: "Evidence reference",
    noEvidence: "No additional reference",
    referenceId: "Reference ID",
    referenceIdHint: "UUID from the approved workflow",
    sha256: "Evidence SHA-256",
    revision: "Approved engine revision",
    acknowledgement:
      "I understand this optional override becomes an immutable audited decision.",
    privacy:
      "References only. Never paste a password, filename, path, document text, or secret here.",
    password:
      "Submit the password through the secure password workflow first, then enter only its queued analysis task ID.",
    apply: "Record audited decision",
    applying: "Recording…",
    unavailable:
      "A live open finding and collection write permission are required.",
    noActions: "No customer action is safe for this finding.",
    success: "Decision recorded in the immutable integrity ledger.",
    history: "Decision history",
    noHistory: "No customer decision has been recorded for this finding.",
    resultingStatus: "Result",
    actions: {
      keep_quarantined: "Keep quarantined",
      exclude: "Exclude from knowledge package",
      retry_new_engine: "Retry with approved engine",
      provide_password: "Use securely submitted password",
      correct_source: "Use corrected source file",
      override: "Optional override",
    },
    evidence: {
      artifact_sha256: "Artifact SHA-256",
      analysis_task: "Secure analysis task",
      source_file: "Corrected source file",
      engine_revision: "Engine revision proof",
      support_case: "Support case",
    },
  },
  ko: {
    title: "선택적 고객 결정",
    intro:
      "자동 파이프라인은 이미 완료됐거나 안전하게 격리된 상태입니다. 구조화된 출처 참조가 고객 선택을 뒷받침할 때만 사용하세요.",
    decision: "결정",
    reason: "감사 사유 코드",
    evidenceKind: "근거 참조",
    noEvidence: "추가 참조 없음",
    referenceId: "참조 ID",
    referenceIdHint: "승인된 워크플로에서 발급된 UUID",
    sha256: "근거 SHA-256",
    revision: "승인된 엔진 리비전",
    acknowledgement:
      "이 선택적 재정의가 변경 불가능한 감사 결정으로 기록됨을 이해합니다.",
    privacy:
      "참조값만 입력하세요. 비밀번호, 파일명, 경로, 문서 본문 또는 비밀값은 절대 붙여 넣지 마세요.",
    password:
      "먼저 보안 비밀번호 워크플로로 비밀번호를 제출한 뒤, 생성된 분석 작업 ID만 입력하세요.",
    apply: "감사 결정 기록",
    applying: "기록 중…",
    unavailable: "실제 미해결 항목과 컬렉션 쓰기 권한이 필요합니다.",
    noActions: "이 항목에 안전하게 적용할 수 있는 고객 선택이 없습니다.",
    success: "결정이 변경 불가능한 무결성 원장에 기록됐습니다.",
    history: "결정 이력",
    noHistory: "이 항목에 기록된 고객 결정이 없습니다.",
    resultingStatus: "결과",
    actions: {
      keep_quarantined: "격리 상태 유지",
      exclude: "지식 패키지에서 제외",
      retry_new_engine: "승인된 새 엔진으로 재시도",
      provide_password: "보안 제출된 비밀번호 사용",
      correct_source: "수정된 원문 파일 사용",
      override: "선택적 재정의",
    },
    evidence: {
      artifact_sha256: "산출물 SHA-256",
      analysis_task: "보안 분석 작업",
      source_file: "수정된 원문 파일",
      engine_revision: "엔진 리비전 근거",
      support_case: "지원 사례",
    },
  },
} as const;

type IntegrityDecisionPanelProps = {
  locale: StructaraLocale;
  collectionId?: string;
  finding?: CollectionIntegrityFinding;
  decisions: readonly CollectionIntegrityDecision[];
  onCommitted: (decision: CollectionIntegrityDecision) => void;
};

export function IntegrityDecisionPanel(props: IntegrityDecisionPanelProps) {
  const targetKey = props.finding
    ? `${props.finding.target_type}:${props.finding.target_id}`
    : "none";
  return <IntegrityDecisionForm key={targetKey} {...props} />;
}

function IntegrityDecisionForm({
  locale,
  collectionId,
  finding,
  decisions,
  onCommitted,
}: IntegrityDecisionPanelProps) {
  const copy = COPY[locale];
  const allowedActions = useMemo(
    () => finding?.allowed_actions ?? [],
    [finding?.allowed_actions],
  );
  const [action, setAction] = useState<CollectionIntegrityDecisionAction | "">(
    allowedActions[0] ?? "",
  );
  const [evidenceKind, setEvidenceKind] = useState<EvidenceKind>("none");
  const [referenceId, setReferenceId] = useState("");
  const [sha256, setSha256] = useState("");
  const [revision, setRevision] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [success, setSuccess] = useState(false);

  const availableEvidenceKinds = evidenceKindsForAction(action);
  const targetHistory = finding
    ? decisions.filter(
        (decision) =>
          decision.target_type === finding.target_type &&
          decision.target_id === finding.target_id,
      )
    : [];
  const enabled = Boolean(collectionId && finding && action);
  const canSubmit =
    enabled &&
    !pending &&
    evidenceIsComplete(evidenceKind, referenceId, sha256, revision) &&
    (action !== "override" || acknowledged);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!collectionId || !finding || !action || !canSubmit) return;
    setPending(true);
    setError(undefined);
    setSuccess(false);
    try {
      const decision = await createCollectionIntegrityDecision(collectionId, {
        target_type: finding.target_type,
        target_id: finding.target_id,
        action,
        reason_code: INTEGRITY_REASON_BY_ACTION[action],
        evidence_reference: buildEvidenceReference(
          evidenceKind,
          referenceId,
          sha256,
          revision,
        ),
        acknowledge_override: action === "override" && acknowledged,
      });
      setSuccess(true);
      onCommitted(decision);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The integrity decision could not be recorded.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="integrity-override" open={Boolean(finding)}>
      <summary>{copy.title}</summary>
      <p>{copy.intro}</p>

      <form onSubmit={(event) => void submit(event)}>
        <label>
          <span>{copy.decision}</span>
          <select
            value={action}
            disabled={!enabled}
            onChange={(event) => {
              const next = event.target.value as CollectionIntegrityDecisionAction;
              setAction(next);
              setEvidenceKind(defaultEvidenceKind(next));
              setReferenceId("");
              setSha256("");
              setRevision("");
              setAcknowledged(false);
              setError(undefined);
              setSuccess(false);
            }}
          >
            {allowedActions.length === 0 && <option value="">—</option>}
            {allowedActions.map((value) => (
              <option key={value} value={value}>
                {copy.actions[value]}
              </option>
            ))}
          </select>
        </label>

        {action && (
          <dl className="integrity-decision-contract">
            <div>
              <dt>{copy.reason}</dt>
              <dd>
                <code>{INTEGRITY_REASON_BY_ACTION[action]}</code>
              </dd>
            </div>
          </dl>
        )}

        {availableEvidenceKinds.length > 1 && (
          <label>
            <span>{copy.evidenceKind}</span>
            <select
              value={evidenceKind}
              disabled={!enabled}
              onChange={(event) => {
                setEvidenceKind(event.target.value as EvidenceKind);
                setReferenceId("");
                setSha256("");
                setRevision("");
              }}
            >
              {availableEvidenceKinds.map((value) => (
                <option key={value} value={value}>
                  {value === "none" ? copy.noEvidence : copy.evidence[value]}
                </option>
              ))}
            </select>
          </label>
        )}

        {requiresReferenceId(evidenceKind) && (
          <label>
            <span>{copy.referenceId}</span>
            <input
              value={referenceId}
              disabled={!enabled}
              inputMode="text"
              autoComplete="off"
              placeholder={copy.referenceIdHint}
              onChange={(event) => setReferenceId(event.target.value)}
            />
          </label>
        )}
        {requiresSha256(evidenceKind) && (
          <label>
            <span>{copy.sha256}</span>
            <input
              value={sha256}
              disabled={!enabled}
              inputMode="text"
              autoComplete="off"
              maxLength={64}
              placeholder="64 lowercase hexadecimal characters"
              onChange={(event) => setSha256(event.target.value.trim().toLowerCase())}
            />
          </label>
        )}
        {evidenceKind === "engine_revision" && (
          <label>
            <span>{copy.revision}</span>
            <input
              value={revision}
              disabled={!enabled}
              inputMode="text"
              autoComplete="off"
              maxLength={120}
              placeholder="engine-name@immutable-revision"
              onChange={(event) => setRevision(event.target.value.trim())}
            />
          </label>
        )}
        {action === "provide_password" && (
          <p className="integrity-decision-safety">
            <LockKey size={17} aria-hidden="true" />
            {copy.password}
          </p>
        )}
        {action === "override" && (
          <label className="integrity-decision-acknowledgement">
            <input
              type="checkbox"
              checked={acknowledged}
              disabled={!enabled}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>{copy.acknowledgement}</span>
          </label>
        )}

        <p className="integrity-decision-safety">
          <Warning size={17} aria-hidden="true" />
          {copy.privacy}
        </p>
        <button type="submit" disabled={!canSubmit}>
          {pending ? copy.applying : copy.apply}
        </button>
        {!enabled && (
          <small>{finding ? copy.noActions : copy.unavailable}</small>
        )}
        {error && (
          <p className="integrity-decision-message" role="alert" data-state="error">
            {error}
          </p>
        )}
        {success && (
          <p className="integrity-decision-message" role="status" data-state="success">
            <CheckCircle size={17} weight="fill" aria-hidden="true" />
            {copy.success}
          </p>
        )}
      </form>

      <section className="integrity-decision-history" aria-label={copy.history}>
        <h3>{copy.history}</h3>
        {targetHistory.length === 0 ? (
          <p>{copy.noHistory}</p>
        ) : (
          <ol>
            {targetHistory.map((decision) => (
              <li key={decision.id}>
                <span>
                  <strong>{copy.actions[decision.action]}</strong>
                  <code>{decision.reason_code}</code>
                </span>
                <span>
                  <small>{copy.resultingStatus}</small>
                  <b>{decision.resulting_status}</b>
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </details>
  );
}

function evidenceKindsForAction(
  action: CollectionIntegrityDecisionAction | "",
): readonly EvidenceKind[] {
  if (action === "keep_quarantined" || action === "exclude") {
    return ["none", "artifact_sha256", "support_case"];
  }
  if (action === "retry_new_engine") return ["engine_revision"];
  if (action === "provide_password") return ["analysis_task"];
  if (action === "correct_source") return ["source_file"];
  if (action === "override") return ["artifact_sha256", "support_case"];
  return ["none"];
}

function defaultEvidenceKind(
  action: CollectionIntegrityDecisionAction | "",
): EvidenceKind {
  return evidenceKindsForAction(action)[0] ?? "none";
}

function requiresReferenceId(kind: EvidenceKind): boolean {
  return kind === "analysis_task" || kind === "source_file" || kind === "support_case";
}

function requiresSha256(kind: EvidenceKind): boolean {
  return kind === "artifact_sha256" || kind === "source_file" || kind === "engine_revision";
}

function evidenceIsComplete(
  kind: EvidenceKind,
  referenceId: string,
  sha256: string,
  revision: string,
): boolean {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const digest = /^[0-9a-f]{64}$/;
  const revisionCode = /^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,119}$/;
  if (kind === "none") return true;
  if (kind === "artifact_sha256") return digest.test(sha256);
  if (kind === "analysis_task" || kind === "support_case") {
    return uuid.test(referenceId);
  }
  if (kind === "source_file") {
    return uuid.test(referenceId) && digest.test(sha256);
  }
  return digest.test(sha256) && revisionCode.test(revision);
}

function buildEvidenceReference(
  kind: EvidenceKind,
  referenceId: string,
  sha256: string,
  revision: string,
): CollectionIntegrityEvidenceReference | undefined {
  if (kind === "none") return undefined;
  if (kind === "artifact_sha256") return { kind, sha256 };
  if (kind === "analysis_task" || kind === "support_case") {
    return { kind, reference_id: referenceId };
  }
  if (kind === "source_file") {
    return { kind, reference_id: referenceId, sha256 };
  }
  return { kind, sha256, revision };
}
