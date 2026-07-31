import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";

export default function SsoPage() {
  return (
    <main id="main-content" className="st-auth-simple">
      <Link href="/">
        <BrandMark />
      </Link>
      <form>
        <p>Enterprise access</p>
        <h1>Continue with your organization.</h1>
        <span>
          Organization discovery becomes available after a production identity
          provider is configured for the deployment.
        </span>
        <label>
          <span>Work email</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            placeholder="Identity provider is not configured"
            disabled
          />
        </label>
        <button
          type="button"
          className="st-app-primary"
          disabled
          title="SSO requires a configured production identity provider."
          data-auth-external-gate
        >
          Continue to SSO
        </button>
        <Link href="/login">Use password sign in</Link>
      </form>
    </main>
  );
}
