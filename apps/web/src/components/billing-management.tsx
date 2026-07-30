"use client";

import { CreditCard, Warning } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest, ApiError } from "@/lib/api-client";

interface CreditPack {
  code: string;
  amount_minor: number;
  currency: string;
  credits: string | number;
}

interface Checkout {
  id: string;
  provider: string;
  provider_checkout_id?: string | null;
  pack_code: string;
  amount_minor: number;
  currency: string;
  credits: string | number;
  status: string;
  checkout_url?: string | null;
  expires_at: string;
  completed_at?: string | null;
  created_at: string;
}

interface Payment {
  id: string;
  checkout_id: string;
  provider: string;
  provider_payment_id: string;
  amount_minor: number;
  currency: string;
  credits: string | number;
  status: string;
  paid_at?: string | null;
  created_at: string;
}

export function BillingManagement() {
  const queryClient = useQueryClient();
  const [checkout, setCheckout] = useState<Checkout>();
  const packs = useQuery({
    queryKey: ["billing", "credit-packs"],
    queryFn: () => apiRequest<CreditPack[]>("/v1/billing/credit-packs"),
    retry: (attempt, error) =>
      !(error instanceof ApiError && error.code === "PAYMENTS_UNAVAILABLE") &&
      attempt < 2,
  });
  const payments = useQuery({
    queryKey: ["billing", "payments"],
    queryFn: () => apiRequest<Payment[]>("/v1/billing/payments?limit=20"),
  });
  const createCheckout = useMutation({
    mutationFn: (packCode: string) =>
      apiRequest<Checkout>("/v1/billing/checkouts", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ pack_code: packCode }),
      }),
    onSuccess: (value) => {
      setCheckout(value);
      void queryClient.invalidateQueries({ queryKey: ["billing", "payments"] });
    },
  });

  const paymentsUnavailable =
    packs.error instanceof ApiError &&
    packs.error.code === "PAYMENTS_UNAVAILABLE";

  return (
    <div className="billing-management">
      {paymentsUnavailable ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>
            No verified payment provider is connected to this environment.
            Credit purchases remain unavailable rather than simulated.
          </p>
        </div>
      ) : packs.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Loading available credit packs.</p>
        </div>
      ) : packs.isError ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>Credit packs could not be loaded: {packs.error.message}</p>
          <button
            type="button"
            className="secondary-button compact"
            onClick={() => void packs.refetch()}
          >
            Try again
          </button>
        </div>
      ) : (
        <div className="credit-pack-grid">
          {packs.data.map((pack) => (
            <article className="credit-pack-card" key={pack.code}>
              <CreditCard size={18} aria-hidden="true" />
              <strong>{Number(pack.credits).toLocaleString()} credits</strong>
              <span>{formatMoney(pack.amount_minor, pack.currency)}</span>
              <button
                type="button"
                className="secondary-button compact"
                disabled={createCheckout.isPending}
                onClick={() => {
                  setCheckout(undefined);
                  createCheckout.mutate(pack.code);
                }}
              >
                {createCheckout.isPending
                  ? "Preparing checkout…"
                  : "Continue to checkout"}
              </button>
            </article>
          ))}
        </div>
      )}

      {createCheckout.isError && (
        <p className="form-error" role="alert">
          Checkout could not be prepared: {createCheckout.error.message}
        </p>
      )}
      {checkout && (
        <div className="checkout-evidence" role="status">
          <div>
            <strong>Checkout {checkout.status}</strong>
            <small>
              {checkout.provider} · Expires{" "}
              {new Date(checkout.expires_at).toLocaleString("en-US")}
            </small>
          </div>
          {safeCheckoutUrl(checkout.checkout_url) ? (
            <a
              className="primary-button compact"
              href={safeCheckoutUrl(checkout.checkout_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open payment provider
            </a>
          ) : (
            <span className="status-badge neutral">
              Checkout URL unavailable
            </span>
          )}
        </div>
      )}

      <div className="team-subsection">
        <h3>Confirmed payment history</h3>
        {payments.isPending ? (
          <div className="honest-state compact" aria-busy="true">
            <span className="spinner" aria-hidden="true" />
            <p>Loading the payment ledger.</p>
          </div>
        ) : payments.isError ? (
          <div className="honest-state compact">
            <p>The payment ledger could not be loaded.</p>
          </div>
        ) : payments.data.length === 0 ? (
          <div className="honest-state compact">
            <p>No server-confirmed payments are available.</p>
          </div>
        ) : (
          <div className="payment-list">
            {payments.data.map((payment) => (
              <div className="payment-row" key={payment.id}>
                <span>
                  <strong>
                    {Number(payment.credits).toLocaleString()} credits
                  </strong>
                  <small>
                    {payment.provider} ·{" "}
                    {formatMoney(payment.amount_minor, payment.currency)}
                  </small>
                </span>
                <span className="status-badge neutral">{payment.status}</span>
                <time dateTime={payment.paid_at ?? payment.created_at}>
                  {new Date(
                    payment.paid_at ?? payment.created_at,
                  ).toLocaleString("ko-KR")}
                </time>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function formatMoney(amountMinor: number, currency: string): string {
  try {
    return new Intl.NumberFormat("ko-KR", {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(amountMinor / 100);
  } catch {
    return `${amountMinor} ${currency.toUpperCase()} (minor units)`;
  }
}

function safeCheckoutUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
}
