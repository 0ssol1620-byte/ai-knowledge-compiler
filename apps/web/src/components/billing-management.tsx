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
            이 환경에는 검증된 결제 사업자가 연결되지 않았습니다. 크레딧 구매를
            가장하지 않습니다.
          </p>
        </div>
      ) : packs.isPending ? (
        <div className="honest-state compact" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <p>구매 가능한 크레딧 팩을 확인하고 있습니다.</p>
        </div>
      ) : packs.isError ? (
        <div className="honest-state compact">
          <Warning size={20} aria-hidden="true" />
          <p>크레딧 팩을 불러오지 못했습니다: {packs.error.message}</p>
          <button
            type="button"
            className="secondary-button compact"
            onClick={() => void packs.refetch()}
          >
            다시 시도
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
                {createCheckout.isPending ? "결제 준비 중…" : "결제 시작"}
              </button>
            </article>
          ))}
        </div>
      )}

      {createCheckout.isError && (
        <p className="form-error" role="alert">
          결제를 준비하지 못했습니다: {createCheckout.error.message}
        </p>
      )}
      {checkout && (
        <div className="checkout-evidence" role="status">
          <div>
            <strong>Checkout {checkout.status}</strong>
            <small>
              {checkout.provider} ·{" "}
              {new Date(checkout.expires_at).toLocaleString("ko-KR")} 만료
            </small>
          </div>
          {safeCheckoutUrl(checkout.checkout_url) ? (
            <a
              className="primary-button compact"
              href={safeCheckoutUrl(checkout.checkout_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              결제 사업자 페이지 열기
            </a>
          ) : (
            <span className="status-badge neutral">결제 URL 없음</span>
          )}
        </div>
      )}

      <div className="team-subsection">
        <h3>확정된 결제 기록</h3>
        {payments.isPending ? (
          <div className="honest-state compact" aria-busy="true">
            <span className="spinner" aria-hidden="true" />
            <p>결제 원장을 확인하고 있습니다.</p>
          </div>
        ) : payments.isError ? (
          <div className="honest-state compact">
            <p>결제 원장을 불러오지 못했습니다.</p>
          </div>
        ) : payments.data.length === 0 ? (
          <div className="honest-state compact">
            <p>서버가 확인한 결제 기록이 없습니다.</p>
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
