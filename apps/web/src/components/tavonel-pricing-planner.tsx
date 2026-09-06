"use client";

import { useEffect, useMemo, useState } from "react";

import { CANONICAL_PLANS } from "@/lib/billing-catalog";
import { recordPublicProductEvent } from "@/lib/public-product-analytics";

const STANDARD_PAGE_USD = 0.04;
const MAXIMUM_PAGE_USD = 0.06;

function usd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function TavonelPricingPlanner() {
  const [pages, setPages] = useState(348);
  const [complexRatio, setComplexRatio] = useState(11);
  const estimate = useMemo(() => {
    const complexPages = Math.ceil(pages * (complexRatio / 100));
    const standard = pages * STANDARD_PAGE_USD;
    const expected = standard + complexPages * (MAXIMUM_PAGE_USD - STANDARD_PAGE_USD);
    const maximum = pages * MAXIMUM_PAGE_USD;
    return { complexPages, expected, maximum };
  }, [complexRatio, pages]);

  useEffect(() => {
    recordPublicProductEvent("pricing_viewed");
  }, []);

  return (
    <section className="tv-pricing-system" aria-labelledby="pricing-plans-title">
      <header>
        <p className="tv-context-label">Pages + dollars</p>
        <h2 id="pricing-plans-title">Processing from $0.04 per page.</h2>
        <p>
          Every run shows an estimate and a maximum charge before processing.
          Complex routing adds cost only to pages that require it.
        </p>
      </header>

      <div className="tv-plan-ledger tv-plan-ledger-five">
        {CANONICAL_PLANS.map((plan) => (
          <article key={plan.name}>
            <span>{plan.cadence}</span>
            <h3>{plan.name}</h3>
            <strong className="tv-plan-price">{plan.price}</strong>
            <p>
              {plan.includedPages === null
                ? "Usage and throughput set only after qualification"
                : `${plan.includedPages.toLocaleString()} standard pages included`}
            </p>
            <ul>
              {plan.includes.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </article>
        ))}
      </div>

      <div className="tv-credit-planner">
        <div>
          <p className="tv-context-label">Pre-run calculator</p>
          <h2>Know the boundary before you compile.</h2>
          <label>
            <span>Detected pages <strong>{pages.toLocaleString()}</strong></span>
            <input
              type="range"
              min="1"
              max="10000"
              step="1"
              value={pages}
              onChange={(event) => setPages(Number(event.currentTarget.value))}
            />
          </label>
          <label>
            <span>Complex-page estimate <strong>{complexRatio}%</strong></span>
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              value={complexRatio}
              onChange={(event) => setComplexRatio(Number(event.currentTarget.value))}
            />
          </label>
          <p>
            {estimate.complexPages.toLocaleString()} pages may require vision or
            precision escalation. You can lower the hard cap before starting.
          </p>
        </div>
        <aside aria-live="polite">
          <span>Estimated compile</span>
          <dl>
            <div><dt>Standard floor</dt><dd>{usd(pages * STANDARD_PAGE_USD)}</dd></div>
            <div><dt>Estimated charge</dt><dd>{usd(estimate.expected)}</dd></div>
            <div><dt>Maximum charge</dt><dd>{usd(estimate.maximum)}</dd></div>
          </dl>
          <p>No run may settle above the approved maximum charge.</p>
          <details>
            <summary>Internal usage details</summary>
            <p>1 internal processing unit = $0.01. Units support reservations, retries, release, and cost accounting; they are not the primary sales unit.</p>
          </details>
        </aside>
      </div>
      <p className="tv-pricing-hypothesis">
        Developer and Team are the canonical launch hypotheses. Scale and
        Enterprise remain qualification-only until measured P50/P95 COGS and
        owner approval establish their allowance and commercial rate.
      </p>
    </section>
  );
}
