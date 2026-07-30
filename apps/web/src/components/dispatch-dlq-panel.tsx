"use client";

import {
  ArrowBendDownRight,
  ArrowClockwise,
  CheckCircle,
  Prohibit,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { apiRequest } from "@/lib/api-client";

interface DispatchDeadLetter {
  original_event_id: string;
  original_job_id: string;
  attempts: number;
  last_error: string | null;
  dead_lettered_at: string;
  disposition: "closed" | "fallback" | null;
  state_sha256: string;
}

type RecoveryAction = "replay" | "fallback" | "close";

const fallbackProfiles = [
  ["parse_private_v1", "Private / native-only"],
  ["parse_balanced_v1", "Balanced"],
  ["parse_precision_v1", "Precision"],
  ["parse_fast_v1", "Fast"],
  ["parse_long_v1", "Long document"],
] as const;

export function DispatchDlqPanel() {
  const [selectedId, setSelectedId] = useState<string>();
  const [action, setAction] = useState<RecoveryAction>("replay");
  const [route, setRoute] = useState("parse_private_v1");
  const [reason, setReason] = useState("manual_recovery");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const deadLetters = useQuery({
    queryKey: ["dispatch-dlq"],
    queryFn: () =>
      apiRequest<DispatchDeadLetter[]>("/v1/admin/dispatch-dlq?limit=100"),
    refetchInterval: 30_000,
  });
  const selected = useMemo(
    () => deadLetters.data?.find((row) => row.original_event_id === selectedId),
    [deadLetters.data, selectedId],
  );
  const recovery = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error("Select a dead-letter item first.");
      const idempotencyKey = crypto.randomUUID();
      if (action === "replay") {
        return apiRequest(
          `/v1/admin/dispatch-dlq/${selected.original_event_id}/replay`,
          { method: "POST", idempotencyKey },
        );
      }
      if (action === "fallback") {
        return apiRequest(
          `/v1/admin/dispatch-dlq/${selected.original_event_id}/fallback`,
          {
            method: "POST",
            idempotencyKey,
            body: JSON.stringify({
              expected_state_sha256: selected.state_sha256,
              fallback_route_profile: route,
              reason_code: reason,
              note,
            }),
          },
        );
      }
      return apiRequest(
        `/v1/admin/dispatch-dlq/${selected.original_event_id}/close`,
        {
          method: "POST",
          idempotencyKey,
          body: JSON.stringify({
            expected_state_sha256: selected.state_sha256,
            reason_code: reason,
            note,
          }),
        },
      );
    },
    onSuccess: async () => {
      setSelectedId(undefined);
      setConfirmed(false);
      setNote("");
      await deadLetters.refetch();
    },
  });
  const openRows = deadLetters.data?.filter((row) => !row.disposition) ?? [];

  return (
    <section className="panel admin-table-panel dlq-panel">
      <div className="panel-heading">
        <div>
          <h2>Dispatch dead-letter queue</h2>
          <p>
            Retry, route to an approved fallback profile, or close with an
            audited disposition. Payload content is never displayed.
          </p>
        </div>
        <span className="dlq-count">{openRows.length} open</span>
      </div>

      {deadLetters.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Loading durable dispatch failures...</p>
        </div>
      ) : deadLetters.isError ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>{deadLetters.error.message}</p>
        </div>
      ) : openRows.length === 0 ? (
        <div className="honest-state compact">
          <CheckCircle size={20} weight="fill" aria-hidden="true" />
          <p>No open dispatch dead letters.</p>
        </div>
      ) : (
        <div className="admin-table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Job</th>
                <th>Attempts</th>
                <th>Last error</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {openRows.map((row) => (
                <tr key={row.original_event_id}>
                  <td>
                    <code>{compactId(row.original_event_id)}</code>
                  </td>
                  <td>
                    <code>{compactId(row.original_job_id)}</code>
                  </td>
                  <td>{row.attempts}</td>
                  <td>{row.last_error ?? "Unavailable"}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary-button compact"
                      onClick={() => {
                        setSelectedId(row.original_event_id);
                        setConfirmed(false);
                        setNote("");
                      }}
                    >
                      Preview recovery
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="dlq-recovery-preview" role="region" aria-live="polite">
          <div className="dlq-preview-evidence">
            <span>
              <small>Event</small>
              <code>{selected.original_event_id}</code>
            </span>
            <span>
              <small>State evidence</small>
              <code>{selected.state_sha256}</code>
            </span>
            <span>
              <small>Dead-lettered</small>
              <strong>
                {new Date(selected.dead_lettered_at).toLocaleString()}
              </strong>
            </span>
          </div>
          <fieldset className="dlq-action-selector">
            <legend>Recovery action</legend>
            {(["replay", "fallback", "close"] as const).map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="dlq-action"
                  value={value}
                  checked={action === value}
                  onChange={() => {
                    setAction(value);
                    setReason(
                      value === "close"
                        ? "manual_resolution"
                        : "manual_recovery",
                    );
                    setConfirmed(false);
                  }}
                />
                <span>{value}</span>
              </label>
            ))}
          </fieldset>
          {action === "fallback" && (
            <label className="field">
              <span>Approved fallback profile</span>
              <select
                value={route}
                onChange={(event) => setRoute(event.currentTarget.value)}
              >
                {fallbackProfiles.map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {action !== "replay" && (
            <>
              <label className="field">
                <span>Reason code</span>
                <select
                  value={reason}
                  onChange={(event) => setReason(event.currentTarget.value)}
                >
                  {(action === "close"
                    ? [
                        "manual_resolution",
                        "non_retryable",
                        "invalid_payload",
                        "duplicate",
                        "superseded",
                      ]
                    : [
                        "manual_recovery",
                        "provider_unavailable",
                        "route_exhausted",
                        "policy_override",
                      ]
                  ).map((value) => (
                    <option value={value} key={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Operator note</span>
                <textarea
                  rows={3}
                  value={note}
                  maxLength={2_000}
                  onChange={(event) => setNote(event.currentTarget.value)}
                  placeholder="Why is this disposition safe?"
                />
              </label>
            </>
          )}
          <label className="dlq-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.currentTarget.checked)}
            />
            I reviewed the event, job, state hash, and selected recovery action.
          </label>
          <div className="dlq-recovery-actions">
            <button
              type="button"
              className="secondary-button compact"
              onClick={() => setSelectedId(undefined)}
            >
              Cancel
            </button>
            <button
              type="button"
              className={
                action === "close"
                  ? "danger-button compact"
                  : "primary-button compact"
              }
              disabled={
                recovery.isPending ||
                !confirmed ||
                (action !== "replay" && note.trim().length < 3)
              }
              onClick={() => recovery.mutate()}
            >
              {action === "replay" ? (
                <ArrowClockwise size={14} aria-hidden="true" />
              ) : action === "fallback" ? (
                <ArrowBendDownRight size={14} aria-hidden="true" />
              ) : (
                <Prohibit size={14} aria-hidden="true" />
              )}
              {recovery.isPending ? "Applying..." : `Confirm ${action}`}
            </button>
          </div>
          {recovery.isError && (
            <p className="admin-action-error" role="alert">
              {recovery.error.message}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function compactId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}
