"use client";

import { FileText, Warning } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";

import { apiRequest, ApiError } from "@/lib/api-client";

interface CreditPack {
  code: string;
  amount_minor: number;
  currency: string;
  credits: string | number;
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
  const paymentsUnavailable =
    packs.error instanceof ApiError &&
    packs.error.code === "PAYMENTS_UNAVAILABLE";

  return (
    <div className="billing-management">
      <div className="honest-state compact">
        <FileText size={20} aria-hidden="true" />
        <p>
          Customer processing is quoted at $0.04 per standard page and never
          above $0.06 per routed page. Page-priced checkout is not enabled in
          this environment, so no legacy credit pack can be purchased here.
        </p>
      </div>
      {paymentsUnavailable ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>
            No verified payment provider is connected to this environment.
            Page-priced purchases remain unavailable rather than simulated.
          </p>
        </div>
      ) : packs.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>Loading the internal billing catalog.</p>
        </div>
      ) : packs.isError ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>The internal billing catalog could not be loaded: {packs.error.message}</p>
          <button
            type="button"
            className="secondary-button compact"
            onClick={() => void packs.refetch()}
          >
            Try again
          </button>
        </div>
      ) : (
        <details className="billing-internal-catalog">
          <summary>Advanced · legacy internal units</summary>
          <div className="credit-pack-grid">
            {packs.data.map((pack) => (
              <article className="credit-pack-card" key={pack.code}>
                <strong>{Number(pack.credits).toLocaleString()} internal units</strong>
                <span>{formatMoney(pack.amount_minor, pack.currency)} legacy catalog amount</span>
                <small>Not available for checkout</small>
              </article>
            ))}
          </div>
        </details>
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
                    {formatMoney(payment.amount_minor, payment.currency)}
                  </strong>
                  <small>
                    {payment.provider} · confirmed payment
                  </small>
                  <details><summary>Advanced receipt</summary>{Number(payment.credits).toLocaleString()} internal units</details>
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
