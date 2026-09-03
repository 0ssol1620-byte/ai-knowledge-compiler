export const STANDARD_PAGE_RATE_USD = 0.04;
export const ROUTED_PAGE_RATE_USD = 0.06;

export type CustomerChargeQuote = {
  minimum: number;
  estimated: number;
  maximum: number;
};

export function customerChargeQuote(
  totalPages: number,
  nativePages: number,
): CustomerChargeQuote {
  const total = Math.max(0, Math.trunc(totalPages));
  const native = Math.min(total, Math.max(0, Math.trunc(nativePages)));
  const routed = total - native;
  return {
    minimum: roundCurrency(total * STANDARD_PAGE_RATE_USD),
    estimated: roundCurrency(
      native * STANDARD_PAGE_RATE_USD + routed * ROUTED_PAGE_RATE_USD,
    ),
    maximum: roundCurrency(total * ROUTED_PAGE_RATE_USD),
  };
}

export function formatUsd(value: number, locale = "en-US"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function roundCurrency(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}
