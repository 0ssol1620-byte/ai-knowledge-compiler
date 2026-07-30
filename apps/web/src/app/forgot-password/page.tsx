import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";

export default function ForgotPasswordPage() {
  return (
    <main id="main-content" className="st-auth-simple">
      <Link href="/">
        <BrandMark />
      </Link>
      <form>
        <p>Account recovery</p>
        <h1>Reset your password.</h1>
        <span>
          Enter your email. The response is identical whether an account exists
          or not.
        </span>
        <label>
          <span>Email</span>
          <input type="email" name="email" autoComplete="email" required />
        </label>
        <button type="submit" className="st-app-primary">
          Send recovery instructions
        </button>
        <Link href="/login">Return to sign in</Link>
      </form>
    </main>
  );
}
