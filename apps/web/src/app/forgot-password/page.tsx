import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";

export default function ForgotPasswordPage() {
  return (
    <main id="main-content" className="tv-auth-simple">
      <Link href="/">
        <BrandMark />
      </Link>
      <form>
        <p>Account recovery</p>
        <h1>Reset your password.</h1>
        <span>
          Recovery delivery becomes available after the production email service
          is configured. This repository release candidate does not send email.
        </span>
        <label>
          <span>Email</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            placeholder="Email delivery is not configured"
            disabled
          />
        </label>
        <button
          type="button"
          className="tv-app-primary"
          disabled
          title="Recovery requires the production email service."
          data-auth-external-gate
        >
          Send recovery instructions
        </button>
        <Link href="/login">Return to sign in</Link>
      </form>
    </main>
  );
}
