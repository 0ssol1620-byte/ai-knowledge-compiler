"use client";

import {
  ArrowCounterClockwise,
  CheckCircle,
  Cube,
  Crown,
  Prohibit,
  RocketLaunch,
  ShieldCheck,
  Warning,
  X,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useId, useRef, useState } from "react";

import { apiRequest } from "@/lib/api-client";
import { useDialogFocus } from "@/lib/use-dialog-focus";

type Lifecycle = "candidate" | "champion" | "fallback" | "retired";
type ModelAction = "promote" | "rollback" | "retire";

interface RegistryModel {
  id: string;
  endpoint: string;
  model_id: string;
  revision: string;
  adapter_version: string;
  enabled: boolean;
  canary_percent: number;
  lifecycle_state: Lifecycle;
  generation: number;
  promoted_from_id: string | null;
  benchmark_sha256: string | null;
  recipe_sha256: string | null;
}

interface PendingAction {
  model: RegistryModel;
  action: ModelAction;
}

export function ModelOperationsPanel() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PendingAction>();
  const models = useQuery({
    queryKey: ["admin-models"],
    queryFn: () => apiRequest<RegistryModel[]>("/v1/admin/models"),
    refetchInterval: 30_000,
  });
  const mutation = useMutation({
    mutationFn: ({
      action,
      model,
      payload,
    }: PendingAction & { payload: Record<string, unknown> }) =>
      apiRequest(`/v1/admin/models/${model.id}/${action}`, {
        method: "POST",
        body: JSON.stringify(payload),
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: async () => {
      setSelected(undefined);
      await queryClient.invalidateQueries({ queryKey: ["admin-models"] });
    },
  });

  return (
    <section className="panel model-operations-panel">
      <div className="panel-heading">
        <div>
          <h2>Model lifecycle</h2>
          <p>
            Verify approval evidence and generation locks before atomically
            changing Champion, rollback fallback, or deprecated status.
          </p>
        </div>
        <span className="governance-seal">
          <ShieldCheck size={16} weight="fill" aria-hidden="true" />
          Audited changes only
        </span>
      </div>

      {models.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Loading registry status.</p>
        </div>
      ) : models.isError ? (
        <div className="honest-state compact" role="alert">
          <Warning size={20} aria-hidden="true" />
          <p>The model registry could not be loaded.</p>
          <button
            className="secondary-button compact"
            type="button"
            onClick={() => void models.refetch()}
          >
            Try again
          </button>
        </div>
      ) : models.data.length === 0 ? (
        <div className="honest-state compact">
          <Cube size={20} aria-hidden="true" />
          <p>No model recipes are registered.</p>
        </div>
      ) : (
        <div className="model-registry-list">
          {models.data.map((model) => (
            <article className="model-registry-row" key={model.id}>
              <div className="model-registry-identity">
                <span
                  className={clsx(
                    "model-lifecycle-icon",
                    model.lifecycle_state,
                  )}
                  aria-hidden="true"
                >
                  {model.lifecycle_state === "champion" ? (
                    <Crown size={16} weight="fill" />
                  ) : (
                    <Cube size={16} weight="duotone" />
                  )}
                </span>
                <div>
                  <strong>{model.model_id}</strong>
                  <span>
                    {model.endpoint} · {model.adapter_version}
                  </span>
                </div>
              </div>
              <div className="model-registry-evidence">
                <span
                  className={`model-lifecycle-badge ${model.lifecycle_state}`}
                >
                  {model.lifecycle_state}
                </span>
                <span>
                  Generation <strong>{model.generation}</strong>
                </span>
                <span>
                  Canary <strong>{model.canary_percent}%</strong>
                </span>
                <span
                  className={clsx(
                    "recipe-state",
                    model.recipe_sha256 && model.benchmark_sha256
                      ? "verified"
                      : "missing",
                  )}
                >
                  {model.recipe_sha256 && model.benchmark_sha256 ? (
                    <CheckCircle size={13} weight="fill" aria-hidden="true" />
                  ) : (
                    <Warning size={13} weight="fill" aria-hidden="true" />
                  )}
                  {model.recipe_sha256 && model.benchmark_sha256
                    ? "Evidence bound"
                    : "Evidence required"}
                </span>
              </div>
              <code title={model.revision}>{model.revision.slice(0, 12)}</code>
              <div className="model-registry-actions">
                {model.lifecycle_state !== "champion" &&
                  model.lifecycle_state !== "retired" && (
                    <button
                      className="primary-button compact"
                      type="button"
                      onClick={() => setSelected({ model, action: "promote" })}
                    >
                      <RocketLaunch size={13} aria-hidden="true" />
                      Promote
                    </button>
                  )}
                {model.lifecycle_state === "champion" &&
                  model.promoted_from_id && (
                    <button
                      className="secondary-button compact"
                      type="button"
                      onClick={() => setSelected({ model, action: "rollback" })}
                    >
                      <ArrowCounterClockwise size={13} aria-hidden="true" />
                      Roll back
                    </button>
                  )}
                {!["champion", "retired"].includes(model.lifecycle_state) && (
                  <button
                    className="quiet-danger-button"
                    type="button"
                    onClick={() => setSelected({ model, action: "retire" })}
                  >
                    <Prohibit size={13} aria-hidden="true" />
                    Retire
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {selected && (
        <ModelActionDialog
          value={selected}
          pending={mutation.isPending}
          error={mutation.error?.message}
          onClose={() => !mutation.isPending && setSelected(undefined)}
          onConfirm={(payload) => mutation.mutate({ ...selected, payload })}
        />
      )}
    </section>
  );
}

function ModelActionDialog({
  value,
  pending,
  error,
  onClose,
  onConfirm,
}: {
  value: PendingAction;
  pending: boolean;
  error?: string;
  onClose: () => void;
  onConfirm: (payload: Record<string, unknown>) => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useDialogFocus<HTMLElement>({
    open: true,
    onClose,
    initialFocusRef: closeRef,
  });
  const [approvalRef, setApprovalRef] = useState("");
  const [reason, setReason] = useState("");
  const [benchmarkSha, setBenchmarkSha] = useState(
    value.model.benchmark_sha256 ?? "",
  );
  const [recipeSha, setRecipeSha] = useState(value.model.recipe_sha256 ?? "");
  const copy = {
    promote: {
      title: "Promote this model?",
      description:
        "The current Champion will be retained as an immediate rollback fallback, and the change will be recorded in the audit log.",
      submit: "Promote model",
    },
    rollback: {
      title: "Roll back to the previous Champion?",
      description:
        "The current Champion and verified previous fallback will be exchanged in a single transaction.",
      submit: "Roll back model",
    },
    retire: {
      title: "Deprecate this model?",
      description:
        "An active Champion or its only rollback target cannot be deprecated.",
      submit: "Retire model",
    },
  }[value.action];
  const digestPattern = /^sha256:[0-9a-f]{64}$/;
  const valid =
    approvalRef.trim().length >= 3 &&
    reason.trim().length >= 3 &&
    (value.action !== "promote" ||
      (digestPattern.test(benchmarkSha) && digestPattern.test(recipeSha)));

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="modal-card model-action-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={pending}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <div>
            <h2 id={titleId}>{copy.title}</h2>
            <p id={descriptionId}>{copy.description}</p>
          </div>
          <button
            ref={closeRef}
            className="icon-button"
            type="button"
            disabled={pending}
            onClick={onClose}
            aria-label="Close model action"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="model-action-target">
          <span>{value.model.lifecycle_state}</span>
          <strong>{value.model.model_id}</strong>
          <code>generation {value.model.generation}</code>
        </div>
        {value.action === "promote" && (
          <div className="model-action-digests">
            <label className="field">
              <span>Benchmark SHA-256</span>
              <input
                value={benchmarkSha}
                onChange={(event) => setBenchmarkSha(event.currentTarget.value)}
                placeholder={`sha256:${"0".repeat(64)}`}
                spellCheck={false}
                disabled={pending}
              />
            </label>
            <label className="field">
              <span>Recipe SHA-256</span>
              <input
                value={recipeSha}
                onChange={(event) => setRecipeSha(event.currentTarget.value)}
                placeholder={`sha256:${"0".repeat(64)}`}
                spellCheck={false}
                disabled={pending}
              />
            </label>
          </div>
        )}
        <label className="field">
          <span>Approval reference</span>
          <input
            value={approvalRef}
            onChange={(event) => setApprovalRef(event.currentTarget.value)}
            placeholder="CAB-2026-0730"
            disabled={pending}
          />
        </label>
        <label className="field">
          <span>Operator reason</span>
          <textarea
            rows={4}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            placeholder="Record the approval evidence and reason for this change."
            disabled={pending}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={pending}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className={
              value.action === "retire" ? "danger-button" : "primary-button"
            }
            type="button"
            disabled={!valid || pending}
            onClick={() =>
              onConfirm({
                expected_generation: value.model.generation,
                approval_ref: approvalRef.trim(),
                reason: reason.trim(),
                ...(value.action === "promote"
                  ? {
                      benchmark_sha256: benchmarkSha,
                      recipe_sha256: recipeSha,
                    }
                  : {}),
              })
            }
          >
            {pending ? "Applying…" : copy.submit}
          </button>
        </div>
      </section>
    </div>
  );
}
