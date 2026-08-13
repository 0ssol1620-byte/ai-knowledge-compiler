"use client";

import { Copy, Key, Plus, Trash, Warning } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "@/lib/api-client";

interface ApiKeySummary {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

interface CreatedApiKey extends ApiKeySummary {
  key: string;
}

const scopeOptions = [
  "api:read",
  "api:write",
  "events:read",
  "exports:read",
] as const;

/**
 * Real key management against `/v1/api-keys` (owner/admin only on the
 * server, matching `AdminDep` in services/api/src/akc_api/main.py). No
 * frontend surface for this existed before — the backend already supported
 * it.
 */
export function ApiKeyManagement() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["api:read"]);
  const [createdKey, setCreatedKey] = useState<CreatedApiKey>();
  const [revokeId, setRevokeId] = useState<string>();

  const keys = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => apiRequest<ApiKeySummary[]>("/v1/api-keys"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiRequest<CreatedApiKey>("/v1/api-keys", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ name: name.trim(), scopes }),
      }),
    onSuccess: async (created) => {
      setCreatedKey(created);
      setName("");
      setScopes(["api:read"]);
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/v1/api-keys/${id}`, {
        method: "DELETE",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: async () => {
      setRevokeId(undefined);
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const nameValid = name.trim().length > 0 && name.trim().length <= 120;
  const canCreate = nameValid && scopes.length > 0 && !create.isPending;

  return (
    <div className="api-key-management">
      <div className="api-key-create-grid">
        <label className="field">
          <span>Key name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            placeholder="e.g. CI export puller"
            maxLength={120}
            disabled={create.isPending}
          />
        </label>
        <fieldset className="webhook-event-types">
          <legend>Scopes</legend>
          {scopeOptions.map((scope) => (
            <label key={scope}>
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setScopes((current) =>
                    checked
                      ? [...current, scope]
                      : current.filter((value) => value !== scope),
                  );
                }}
              />
              <span>{scope}</span>
            </label>
          ))}
        </fieldset>
        <button
          className="primary-button"
          type="button"
          disabled={!canCreate}
          onClick={() => create.mutate()}
        >
          <Plus size={14} weight="bold" aria-hidden="true" />
          {create.isPending ? "Creating…" : "Create key"}
        </button>
      </div>

      {create.isError && (
        <p className="form-error" role="alert">
          {create.error.message}
        </p>
      )}

      {createdKey && (
        <div className="webhook-secret-once" role="status">
          <Key size={18} weight="fill" aria-hidden="true" />
          <div>
            <strong>{createdKey.name} — shown once</strong>
            <code>{createdKey.key}</code>
            <span>Store this in a secure secrets manager now.</span>
          </div>
          <button
            className="secondary-button compact"
            type="button"
            onClick={() => void navigator.clipboard.writeText(createdKey.key)}
          >
            <Copy size={13} aria-hidden="true" />
            Copy
          </button>
          <button
            className="secondary-button compact"
            type="button"
            onClick={() => setCreatedKey(undefined)}
          >
            Stored
          </button>
        </div>
      )}

      {keys.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Loading API keys.</p>
        </div>
      ) : keys.isError ? (
        <div className="honest-state compact" role="alert">
          <Warning size={20} aria-hidden="true" />
          <p>The API key list could not be loaded.</p>
        </div>
      ) : keys.data.length === 0 ? (
        <div className="honest-state compact">
          <Key size={20} aria-hidden="true" />
          <p>No API keys have been created for this workspace.</p>
        </div>
      ) : (
        <div className="webhook-endpoint-list">
          {keys.data.map((key) => (
            <article className="webhook-endpoint-card" key={key.id}>
              <header>
                <span
                  className={`webhook-health-dot ${key.revoked_at ? "paused" : "active"}`}
                  aria-hidden="true"
                />
                <div>
                  <strong>
                    {key.name} <code>{key.prefix}…</code>
                  </strong>
                  <span>
                    {key.scopes.join(" · ")} · Created{" "}
                    {new Date(key.created_at).toLocaleDateString("en-US")}
                    {key.last_used_at
                      ? ` · Last used ${new Date(key.last_used_at).toLocaleDateString("en-US")}`
                      : " · Never used"}
                  </span>
                </div>
                {!key.revoked_at && (
                  <button
                    className="quiet-danger-button"
                    type="button"
                    onClick={() =>
                      setRevokeId((current) =>
                        current === key.id ? undefined : key.id,
                      )
                    }
                  >
                    <Trash size={13} aria-hidden="true" />
                    Revoke
                  </button>
                )}
                {key.revoked_at && (
                  <span className="status-badge">Revoked</span>
                )}
              </header>
              {revokeId === key.id && (
                <div className="webhook-delete-confirm" role="alert">
                  <Warning size={16} weight="fill" aria-hidden="true" />
                  <span>
                    Revoke this key immediately. Any integration using it will
                    stop authenticating. This cannot be undone.
                  </span>
                  <button
                    className="danger-button compact"
                    type="button"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(key.id)}
                  >
                    Confirm revoke
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
