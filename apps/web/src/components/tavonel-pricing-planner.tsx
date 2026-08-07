"use client";

import { useMemo, useState } from "react";

const plans = [
  {
    name: "Free",
    audience: "Individuals",
    summary: "Try core conversion with short retention.",
    includes: ["Limited pages", "Core conversion", "Short retention"],
  },
  {
    name: "Personal",
    audience: "Individuals",
    summary: "Clean Markdown and personal knowledge projects.",
    includes: ["Clean Markdown", "Basic Obsidian", "Personal projects"],
  },
  {
    name: "Pro",
    audience: "Individuals",
    summary: "Precision processing with proof and connected knowledge.",
    includes: ["Precision routes", "Source comparison", "Notes and graph"],
  },
  {
    name: "Team",
    audience: "Teams",
    summary: "Shared projects, reviewers, API, and audit basics.",
    includes: ["Shared projects", "Review roles", "API and audit"],
  },
  {
    name: "Business",
    audience: "Teams",
    summary: "Higher limits, retention controls, and organization roles.",
    includes: ["Retention controls", "Organization roles", "Priority support"],
  },
  {
    name: "Enterprise",
    audience: "Enterprise",
    summary: "Custom policy, region, deployment, identity, and SLA.",
    includes: ["Custom policy", "VPC or on-prem", "SSO and SCIM"],
  },
] as const;

type Audience = "Individuals" | "Teams" | "Enterprise";

export function TavonelPricingPlanner() {
  const [audience, setAudience] = useState<Audience>("Individuals");
  const [pages, setPages] = useState(2500);
  const [scanRatio, setScanRatio] = useState(20);
  const [precisionRatio, setPrecisionRatio] = useState(15);
  const [knowledgeOutput, setKnowledgeOutput] = useState(true);

  const estimate = useMemo(() => {
    const weighted =
      pages *
      (1 +
        (scanRatio / 100) * 0.7 +
        (precisionRatio / 100) * 1.5 +
        (knowledgeOutput ? 0.15 : 0));
    const lower = Math.ceil((weighted * 0.9) / 100) * 100;
    const upper = Math.ceil((weighted * 1.15) / 100) * 100;
    const recommended =
      pages <= 100
        ? "Free"
        : pages <= 1000
          ? "Personal"
          : pages <= 5000
            ? "Pro"
            : pages <= 20000
              ? "Team"
              : pages <= 100000
                ? "Business"
                : "Enterprise";
    return { lower, upper, recommended };
  }, [knowledgeOutput, pages, precisionRatio, scanRatio]);

  return (
    <section
      className="tv-pricing-system"
      aria-labelledby="pricing-plans-title"
    >
      <header>
        <p className="tv-context-label">Plans and operating controls</p>
        <h2 id="pricing-plans-title">
          Choose the control surface, then size it.
        </h2>
        <div className="tv-audience-switch" role="group" aria-label="Audience">
          {(["Individuals", "Teams", "Enterprise"] as const).map((item) => (
            <button
              type="button"
              key={item}
              aria-pressed={audience === item}
              onClick={() => setAudience(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </header>

      <div className="tv-plan-ledger">
        {plans
          .filter((plan) => plan.audience === audience)
          .map((plan) => (
            <article key={plan.name}>
              <span>{plan.audience}</span>
              <h3>{plan.name}</h3>
              <p>{plan.summary}</p>
              <ul>
                {plan.includes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </article>
          ))}
      </div>

      <div className="tv-credit-planner">
        <div>
          <p className="tv-context-label">Transparent estimate</p>
          <h2>Plan around the pages you actually process.</h2>
          <p>
            This planning model exposes scan, Precision, and knowledge-output
            overhead. It is an estimate, not a quote.
          </p>
          <label>
            <span>
              Monthly pages <strong>{pages.toLocaleString()}</strong>
            </span>
            <input
              type="range"
              min="100"
              max="150000"
              step="100"
              value={pages}
              onChange={(event) => setPages(Number(event.target.value))}
            />
          </label>
          <label>
            <span>
              Scan ratio <strong>{scanRatio}%</strong>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={scanRatio}
              onChange={(event) => setScanRatio(Number(event.target.value))}
            />
          </label>
          <label>
            <span>
              Precision ratio <strong>{precisionRatio}%</strong>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={precisionRatio}
              onChange={(event) =>
                setPrecisionRatio(Number(event.target.value))
              }
            />
          </label>
          <label className="tv-planner-check">
            <input
              type="checkbox"
              checked={knowledgeOutput}
              onChange={(event) => setKnowledgeOutput(event.target.checked)}
            />
            Build knowledge notes and graph output
          </label>
        </div>
        <aside aria-live="polite">
          <span>Estimated operating profile</span>
          <dl>
            <div>
              <dt>Recommended plan</dt>
              <dd>{estimate.recommended}</dd>
            </div>
            <div>
              <dt>Credit range</dt>
              <dd>
                {estimate.lower.toLocaleString()}–
                {estimate.upper.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt>Maximum draw</dt>
              <dd>{estimate.upper.toLocaleString()} credits</dd>
            </div>
          </dl>
          <p>
            Monetary maximum, overage rate, storage extension, and annual
            discount appear only after the owner-approved price book is
            registered.
          </p>
        </aside>
      </div>
    </section>
  );
}
