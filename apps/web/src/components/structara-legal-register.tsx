import {
  ArrowRight,
  CalendarBlank,
  CheckCircle,
  FileText,
  Scales,
  ShieldWarning,
} from "@phosphor-icons/react/dist/ssr";
import type { Route } from "next";
import Link from "next/link";

const legalRoutes = [
  {
    href: "/legal/privacy",
    label: "Privacy",
    purpose:
      "Data categories, purpose, provider boundaries, retention, and rights.",
  },
  {
    href: "/legal/terms",
    label: "Terms",
    purpose:
      "Service scope, source rights, acceptable use, commercial terms, and risk allocation.",
  },
  {
    href: "/legal/subprocessors",
    label: "Subprocessors",
    purpose:
      "Approved production vendors, regions, data categories, and change notice.",
  },
  {
    href: "/legal/third-party-notices",
    label: "Third-party notices",
    purpose:
      "Software, models, datasets, public sources, fonts, and asset attribution.",
  },
] as const;

export function StructaraLegalRegister({ path }: { path: string }) {
  const current = legalRoutes.find((item) => item.href === path);

  return (
    <section
      className="st-legal-register"
      aria-labelledby="legal-register-title"
    >
      <header>
        <div>
          <p className="st-context-label">Legal publication control</p>
          <h2 id="legal-register-title">
            {current?.label ?? "Legal document"} publication status
          </h2>
          <p>
            This route documents the intended product contract and current
            implementation boundary. It is not represented as counsel-approved
            or legally effective until the accountable owner records approval.
          </p>
        </div>
        <span className="st-legal-status">
          <ShieldWarning size={15} weight="fill" aria-hidden="true" />
          Draft · counsel approval required
        </span>
      </header>

      <dl className="st-legal-ledger">
        <div>
          <dt>
            <FileText size={14} aria-hidden="true" /> Document role
          </dt>
          <dd>{current?.purpose ?? "Product-contract documentation"}</dd>
        </div>
        <div>
          <dt>
            <CalendarBlank size={14} aria-hidden="true" /> Public effective date
          </dt>
          <dd>Not assigned</dd>
        </div>
        <div>
          <dt>
            <Scales size={14} aria-hidden="true" /> Approval evidence
          </dt>
          <dd>Owner and independent counsel record required</dd>
        </div>
        <div>
          <dt>
            <CheckCircle size={14} aria-hidden="true" /> Repository status
          </dt>
          <dd>
            Route, metadata, disclosure boundary, and review checklist
            implemented
          </dd>
        </div>
      </dl>

      <nav className="st-legal-route-nav" aria-label="Legal documents">
        {legalRoutes.map((item) => (
          <Link
            key={item.href}
            href={item.href as Route}
            aria-current={item.href === path ? "page" : undefined}
          >
            <span>{item.label}</span>
            <small>{item.purpose}</small>
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        ))}
      </nav>

      <footer>
        <p>
          Production publication remains blocked until entity, jurisdiction,
          privacy contact, processors, pricing, service commitments, and license
          records are approved for the exact release.
        </p>
        <Link href="/company/contact">Request the current review package</Link>
      </footer>
    </section>
  );
}
