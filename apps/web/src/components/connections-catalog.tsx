import {
  ArrowSquareOut,
  Browser,
  Cloud,
  Code,
  Database,
  LockKey,
  PlugsConnected,
  Prohibit,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

const available = [
  {
    title: "Browser file upload",
    detail: "Authenticated multipart intake with local hashing and server verification.",
    icon: Browser,
  },
  {
    title: "Authorized URL import",
    detail: "Server-side fetch with scheme, host, redirect, size, and content controls.",
    icon: Cloud,
  },
  {
    title: "REST API and webhooks",
    detail: "Idempotent upload, job-event, export, and signed delivery workflows.",
    icon: Code,
  },
] as const;

const unavailable = ["Google Drive", "Microsoft SharePoint / OneDrive", "Notion", "Slack"];

export function ConnectionsCatalog() {
  return (
    <div className="connections-catalog">
      <header className="connections-hero">
        <div>
          <p>Connections</p>
          <h1>Source paths, with their real operating state.</h1>
          <span>
            Availability means the current product has an executable path. It does
            not imply that this workspace has configured credentials.
          </span>
        </div>
        <Link className="primary-button" href="/intake" data-app-header-action>
          <PlugsConnected size={16} aria-hidden="true" /> Add sources
        </Link>
      </header>

      <section aria-labelledby="connections-available">
        <header>
          <h2 id="connections-available">Available now</h2>
          <span>Executable, tenant-scoped intake paths</span>
        </header>
        <div className="connections-grid">
          {available.map(({ title, detail, icon: Icon }) => (
            <article key={title}>
              <Icon size={22} weight="duotone" aria-hidden="true" />
              <div><h3>{title}</h3><p>{detail}</p></div>
              <strong data-state="available">Available</strong>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="connections-managed">
        <header>
          <h2 id="connections-managed">Environment-managed</h2>
          <span>Configured by an authorized operator, never in this browser</span>
        </header>
        <div className="connections-grid">
          <article>
            <Database size={22} weight="duotone" aria-hidden="true" />
            <div>
              <h3>S3-compatible object storage</h3>
              <p>Workload or role credentials remain server-side and role-separated.</p>
            </div>
            <strong data-state="managed">Configuration required</strong>
          </article>
        </div>
      </section>

      <section aria-labelledby="connections-unavailable">
        <header>
          <h2 id="connections-unavailable">Not available in this build</h2>
          <span>No decorative logos and no implied OAuth path</span>
        </header>
        <div className="connections-grid compact">
          {unavailable.map((title) => (
            <article key={title}>
              <Prohibit size={20} aria-hidden="true" />
              <div><h3>{title}</h3><p>No executable connector is shipped.</p></div>
              <strong data-state="unavailable">Unavailable</strong>
            </article>
          ))}
        </div>
      </section>

      <aside className="connections-security">
        <LockKey size={20} weight="fill" aria-hidden="true" />
        <div>
          <h2>Secret boundary</h2>
          <p>Provider secrets and storage credentials are not persisted in client state or exposed by this catalog.</p>
        </div>
        <Link href="/security">Security details <ArrowSquareOut size={14} /></Link>
      </aside>
    </div>
  );
}
