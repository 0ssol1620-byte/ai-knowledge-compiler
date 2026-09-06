"use client";

import { ArrowRight, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";

type SubmitState = "idle" | "sending" | "sent" | "error";

export function TavonelContactForm() {
  const [state, setState] = useState<SubmitState>("idle");
  const [error, setError] = useState("");
  const [startedAt] = useState(() => Date.now());

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState("sending");
    setError("");

    const form = event.currentTarget;
    const body = Object.fromEntries(new FormData(form));

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, startedAt }),
      });
      const result = (await response.json()) as { error?: string };
      if (!response.ok)
        throw new Error(result.error || "We could not send your inquiry.");

      form.reset();
      setState("sent");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "We could not send your inquiry. Please try again shortly.",
      );
      setState("error");
    }
  }

  return (
    <section
      className="tv-contact"
      id="contact-form"
      aria-labelledby="contact-title"
    >
      <div className="tv-contact-intro">
        <p className="tv-context-label">Direct line</p>
        <h2 id="contact-title">Tell us what your knowledge needs to become.</h2>
        <p>
          Share the source types, document volume, target outputs, and security
          requirements. Do not include sensitive source material here.
        </p>
        <div className="tv-contact-address">
          <span>General inquiries</span>
          <a href="mailto:hello@tavonel.com">hello@tavonel.com</a>
          <small>
            Personal mailbox addresses are never published or stored with
            inquiries.
          </small>
        </div>
      </div>

      <form
        className="tv-contact-form"
        onSubmit={(event) => void submit(event)}
      >
        <div className="tv-contact-pair">
          <Field
            label="Name"
            name="name"
            autoComplete="name"
            maxLength={80}
            required
          />
          <Field
            label="Work email"
            name="email"
            type="email"
            autoComplete="email"
            maxLength={254}
            required
          />
        </div>
        <Field
          label="Company or organization"
          name="company"
          autoComplete="organization"
          maxLength={120}
        />
        <label className="tv-contact-field">
          <span>Inquiry type</span>
          <select name="topic" defaultValue="sales">
            <option value="sales">Product and pricing</option>
            <option value="support">Product support</option>
            <option value="security">Security review</option>
            <option value="privacy">Privacy</option>
            <option value="partnership">Partnership</option>
          </select>
        </label>
        <label className="tv-contact-field">
          <span>How can we help?</span>
          <textarea
            name="message"
            rows={7}
            minLength={20}
            maxLength={5000}
            placeholder="Include document volume, source types, target outputs, and timing."
            required
          />
        </label>
        <label className="tv-contact-trap" aria-hidden="true">
          Website
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
        <div className="tv-contact-submit">
          <button
            className="tv-button tv-button-dark"
            type="submit"
            disabled={state === "sending"}
          >
            {state === "sending" ? "Sending" : "Send inquiry"}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
          <p>Your information is used only to respond to this inquiry.</p>
        </div>
        <div className="tv-contact-status" aria-live="polite">
          {state === "sent" && (
            <p data-state="success">
              <CheckCircle size={18} aria-hidden="true" />
              Your inquiry is in. We will reply from an official TAVONEL
              address.
            </p>
          )}
          {state === "error" && (
            <p data-state="error">
              <WarningCircle size={18} aria-hidden="true" />
              {error}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}

function Field({
  label,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="tv-contact-field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
