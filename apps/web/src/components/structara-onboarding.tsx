"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileArrowUp,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";

const steps = ["Goal", "Document type", "Privacy", "First upload"] as const;

const choices = {
  Goal: [
    "Clean Markdown",
    "Obsidian Vault",
    "AI / RAG knowledge",
    "Ontology / Graph",
    "Not sure yet",
  ],
  "Document type": [
    "Reports",
    "Research papers",
    "Course materials",
    "Manuals",
    "Contracts",
    "Mixed files",
  ],
  Privacy: [
    "Ask before external processing",
    "Never use external processing",
    "Allow approved providers",
  ],
  "First upload": [
    "Choose files",
    "Use the public sample",
    "Explore the demo first",
  ],
} as const;

export function StructaraOnboarding() {
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const current = steps[step]!;

  return (
    <main id="main-content" className="st-onboarding">
      <header>
        <Link href="/">Structara</Link>
        <span>First knowledge project</span>
        <small>
          {step + 1} / {steps.length}
        </small>
      </header>
      <section>
        <div
          className="st-onboarding-progress"
          aria-label="Onboarding progress"
        >
          {steps.map((label, index) => (
            <span key={label} data-active={index <= step}>
              <i>{index < step ? <Check size={12} /> : index + 1}</i>
              {label}
            </span>
          ))}
        </div>
        <div className="st-onboarding-copy">
          <p>{current}</p>
          <h1>
            {current === "Goal"
              ? "What do you want to build?"
              : current === "Document type"
                ? "What will you compile first?"
                : current === "Privacy"
                  ? "Choose the processing boundary."
                  : "Start with your first source."}
          </h1>
          <span>
            This choice sets helpful defaults. It never locks your project to a
            model or output.
          </span>
        </div>
        <div className="st-onboarding-options">
          {choices[current].map((choice) => (
            <button
              type="button"
              key={choice}
              data-selected={selected[current] === choice}
              onClick={() =>
                setSelected((value) => ({ ...value, [current]: choice }))
              }
            >
              {current === "First upload" && <FileArrowUp size={17} />}
              <span>{choice}</span>
              {selected[current] === choice && <Check size={15} />}
            </button>
          ))}
        </div>
        <footer>
          <button
            type="button"
            disabled={step === 0}
            onClick={() => setStep((value) => value - 1)}
          >
            <ArrowLeft size={14} /> Back
          </button>
          {step < steps.length - 1 ? (
            <button
              type="button"
              className="st-app-primary"
              disabled={!selected[current]}
              onClick={() => setStep((value) => value + 1)}
            >
              Continue <ArrowRight size={14} />
            </button>
          ) : (
            <Link className="st-app-primary" href="/quick-convert">
              Open upload <ArrowRight size={14} />
            </Link>
          )}
        </footer>
      </section>
    </main>
  );
}
