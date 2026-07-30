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
          Enter your work email to discover the approved identity provider.
        </span>
        <label>
          <span>Work email</span>
          <input type="email" name="email" autoComplete="email" required />
        </label>
        <button type="submit" className="st-app-primary">
          Continue to SSO
        </button>
        <Link href="/login">Use password sign in</Link>
      </form>
    </main>
  );
}
