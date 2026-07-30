"use client";

import {
  ArrowClockwise,
  CheckCircle,
  Copy,
  Key,
  LinkSimple,
  Plus,
  Trash,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "@/lib/api-client";

interface WebhookEndpoint {
  id: string;
  url: string;
  event_types: string[];
  active: boolean;
  created_at: string;
}

interface CreatedWebhook extends WebhookEndpoint {
  signing_secret: string;
}

interface Delivery {
  id: string;
  event_type: string;
  status: string;
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  delivered_at: string | null;
}

const eventTypes = [
  "job.completed.v1",
  "job.failed.v1",
  "export.completed.v1",
] as const;

export function WebhookManagement() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>([...eventTypes]);
  const [secret, setSecret] = useState<string>();
  const [deleteId, setDeleteId] = useState<string>();
  const endpoints = useQuery({
    queryKey: ["webhooks"],
    queryFn: () => apiRequest<WebhookEndpoint[]>("/v1/webhooks"),
  });
  const create = useMutation({
    mutationFn: () =>
      apiRequest<CreatedWebhook>("/v1/webhooks", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ url: url.trim(), event_types: events }),
      }),
    onSuccess: async (created) => {
      setSecret(created.signing_secret);
      setUrl("");
      await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
  const update = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiRequest(`/v1/webhooks/${id}`, {
        method: "PATCH",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ active }),
      }),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["webhooks"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/v1/webhooks/${id}`, {
        method: "DELETE",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: async () => {
      setDeleteId(undefined);
      await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });

  return (
    <div className="webhook-management">
      <div className="webhook-create-grid">
        <label className="field">
          <span>HTTPS endpoint</span>
          <input
            type="url"
            value={url}
            onChange={(event) => setUrl(event.currentTarget.value)}
            placeholder="https://hooks.example.com/akc"
            disabled={create.isPending}
          />
        </label>
        <fieldset className="webhook-event-types">
          <legend>Events</legend>
          {eventTypes.map((eventType) => (
            <label key={eventType}>
              <input
                type="checkbox"
                checked={events.includes(eventType)}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setEvents((current) =>
                    checked
                      ? [...current, eventType]
                      : current.filter((value) => value !== eventType),
                  );
                }}
              />
              <span>{eventType}</span>
            </label>
          ))}
        </fieldset>
        <button
          className="primary-button"
          type="button"
          disabled={
            create.isPending ||
            !url.startsWith("https://") ||
            events.length === 0
          }
          onClick={() => create.mutate()}
        >
          <Plus size={14} weight="bold" aria-hidden="true" />
          {create.isPending ? "Creating…" : "Add endpoint"}
        </button>
      </div>

      {secret && (
        <div className="webhook-secret-once" role="status">
          <Key size={18} weight="fill" aria-hidden="true" />
          <div>
            <strong>Signing secret — shown once</strong>
            <code>{secret}</code>
            <span>안전한 비밀 저장소에 지금 보관하세요.</span>
          </div>
          <button
            className="secondary-button compact"
            type="button"
            onClick={() => void navigator.clipboard.writeText(secret)}
          >
            <Copy size={13} aria-hidden="true" />
            Copy
          </button>
          <button
            className="secondary-button compact"
            type="button"
            onClick={() => setSecret(undefined)}
          >
            Stored
          </button>
        </div>
      )}

      {create.isError && (
        <p className="form-error" role="alert">
          {create.error.message}
        </p>
      )}

      {endpoints.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Webhook endpoints를 확인하고 있습니다.</p>
        </div>
      ) : endpoints.isError ? (
        <div className="honest-state compact" role="alert">
          <Warning size={20} aria-hidden="true" />
          <p>Webhook 목록을 불러오지 못했습니다.</p>
        </div>
      ) : endpoints.data.length === 0 ? (
        <div className="honest-state compact">
          <LinkSimple size={20} aria-hidden="true" />
          <p>등록된 Webhook endpoint가 없습니다.</p>
        </div>
      ) : (
        <div className="webhook-endpoint-list">
          {endpoints.data.map((endpoint) => (
            <article className="webhook-endpoint-card" key={endpoint.id}>
              <header>
                <span
                  className={`webhook-health-dot ${endpoint.active ? "active" : "paused"}`}
                  aria-hidden="true"
                />
                <div>
                  <strong>{endpoint.url}</strong>
                  <span>{endpoint.event_types.join(" · ")}</span>
                </div>
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate({
                      id: endpoint.id,
                      active: !endpoint.active,
                    })
                  }
                >
                  {endpoint.active ? "Pause" : "Activate"}
                </button>
                <button
                  className="quiet-danger-button"
                  type="button"
                  onClick={() =>
                    setDeleteId((current) =>
                      current === endpoint.id ? undefined : endpoint.id,
                    )
                  }
                >
                  <Trash size={13} aria-hidden="true" />
                  Delete
                </button>
              </header>
              {deleteId === endpoint.id && (
                <div className="webhook-delete-confirm" role="alert">
                  <Warning size={16} weight="fill" aria-hidden="true" />
                  <span>
                    이 endpoint와 전달 로그를 삭제합니다. 되돌릴 수 없습니다.
                  </span>
                  <button
                    className="danger-button compact"
                    type="button"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(endpoint.id)}
                  >
                    Confirm delete
                  </button>
                </div>
              )}
              <DeliveryLog endpointId={endpoint.id} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function DeliveryLog({ endpointId }: { endpointId: string }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const deliveries = useQuery({
    queryKey: ["webhook-deliveries", endpointId],
    queryFn: () =>
      apiRequest<Delivery[]>(`/v1/webhooks/${endpointId}/deliveries`),
    enabled: expanded,
  });
  const replay = useMutation({
    mutationFn: (deliveryId: string) =>
      apiRequest(`/v1/webhooks/${endpointId}/deliveries/${deliveryId}/replay`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: async () =>
      queryClient.invalidateQueries({
        queryKey: ["webhook-deliveries", endpointId],
      }),
  });

  return (
    <div className="webhook-deliveries">
      <button
        className="webhook-delivery-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <ArrowClockwise size={13} aria-hidden="true" />
        Delivery log
        <span>{expanded ? "Hide" : "Inspect"}</span>
      </button>
      {expanded &&
        (deliveries.isPending ? (
          <p className="muted-copy">전달 로그를 불러오는 중입니다.</p>
        ) : deliveries.isError ? (
          <p className="form-error" role="alert">
            {deliveries.error.message}
          </p>
        ) : deliveries.data.length === 0 ? (
          <p className="muted-copy">아직 전달 기록이 없습니다.</p>
        ) : (
          <div className="webhook-delivery-table-wrap">
            <table className="webhook-delivery-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Event</th>
                  <th>Attempts</th>
                  <th>Last response</th>
                  <th>Next action</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.data.map((delivery) => (
                  <tr key={delivery.id}>
                    <td>
                      <span className={`delivery-status ${delivery.status}`}>
                        {delivery.status === "delivered" && (
                          <CheckCircle
                            size={12}
                            weight="fill"
                            aria-hidden="true"
                          />
                        )}
                        {delivery.status}
                      </span>
                    </td>
                    <td>{delivery.event_type}</td>
                    <td>{delivery.attempts} / 6</td>
                    <td>
                      {delivery.last_status_code ??
                        delivery.last_error ??
                        "Unavailable"}
                    </td>
                    <td>
                      {delivery.status === "dead_letter" ? (
                        <button
                          className="secondary-button compact"
                          type="button"
                          disabled={replay.isPending}
                          onClick={() => replay.mutate(delivery.id)}
                        >
                          Replay
                        </button>
                      ) : (
                        <span className="muted-copy">
                          {delivery.delivered_at
                            ? new Date(delivery.delivered_at).toLocaleString(
                                "ko-KR",
                              )
                            : delivery.next_attempt_at
                              ? new Date(
                                  delivery.next_attempt_at,
                                ).toLocaleString("ko-KR")
                              : "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
