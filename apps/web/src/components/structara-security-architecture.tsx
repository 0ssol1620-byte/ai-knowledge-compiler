import {
  ArrowDown,
  ArrowRight,
  CloudArrowUp,
  Database,
  FileLock,
  Fingerprint,
  HardDrives,
  Key,
  LockKey,
  MagnifyingGlass,
  Queue,
  ShieldCheck,
  ShieldWarning,
  TerminalWindow,
  UserFocus,
  Wrench,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

const controls = [
  {
    threat: "Tenant confusion",
    control: "Tenant-scoped authorization, server checks, PostgreSQL RLS",
    evidence: "Local contract and cross-tenant test coverage",
    status: "implemented",
  },
  {
    threat: "Upload smuggling",
    control: "Allowlist, magic bytes, quarantine, scanner/CDR boundary",
    evidence: "Fail-closed adapters and hostile synthetic fixtures",
    status: "implemented",
  },
  {
    threat: "Parser escape",
    control:
      "Rootless process, read-only filesystem, no network, resource caps",
    evidence:
      "Sandbox runner and timeout tests; production attestation pending",
    status: "mixed",
  },
  {
    threat: "SSRF",
    control: "Isolated URL worker, public-443-only policy, DNS/IP validation",
    evidence: "Redirect and rebinding tests; deployed policy evidence pending",
    status: "mixed",
  },
  {
    threat: "Generated XSS",
    control:
      "Sanitization, URL-scheme allowlist, CSP nonce, download isolation",
    evidence: "Browser security and CSP tests",
    status: "implemented",
  },
  {
    threat: "External model transmission",
    control:
      "Private-first routing, per-workspace consent, deny in Private mode",
    evidence: "Policy tests; production provider configuration pending",
    status: "mixed",
  },
  {
    threat: "Replay / duplicate charge",
    control: "Idempotency keys, request hashes, append-only credit ledger",
    evidence: "Duplicate and conflict contract tests",
    status: "implemented",
  },
  {
    threat: "Retention failure",
    control: "Lifecycle jobs, deletion receipts, consent and version lineage",
    evidence: "Local workflow exists; timed restore/deletion drill pending",
    status: "mixed",
  },
] as const;

export function StructaraSecurityArchitecture() {
  return (
    <section
      className="st-security-architecture"
      aria-labelledby="security-architecture-title"
    >
      <header>
        <div>
          <p className="st-context-label">Actual control boundaries</p>
          <h2 id="security-architecture-title">
            Customer content crosses explicit boundaries—or it does not cross.
          </h2>
          <p>
            This architecture reflects the repository threat model: private by
            default, tenant-scoped authorization, quarantined intake, isolated
            parsers, bounded object grants, evidence validation, and auditable
            deletion. A checked-in control is not presented as a production
            certification.
          </p>
        </div>
        <div
          className="st-security-boundary-legend"
          aria-label="Boundary legend"
        >
          <span>
            <i data-boundary="public" /> Public TLS / identity
          </span>
          <span>
            <i data-boundary="verified" /> Verified object boundary
          </span>
          <span>
            <i data-boundary="external" /> Optional external provider
          </span>
          <span>
            <i data-boundary="privileged" /> Privileged operations
          </span>
        </div>
      </header>

      <div
        className="st-security-system"
        aria-label="Structara security architecture diagram"
      >
        <section className="st-security-zone st-security-zone-browser">
          <span className="st-security-zone-label">User boundary</span>
          <article>
            <UserFocus size={22} aria-hidden="true" />
            <div>
              <strong>Browser</strong>
              <small>Upload, review, export, delete</small>
            </div>
          </article>
          <article>
            <Fingerprint size={22} aria-hidden="true" />
            <div>
              <strong>OIDC / Session</strong>
              <small>Issuer, claims, roles, expiry</small>
            </div>
          </article>
        </section>

        <div className="st-security-flow-arrow" aria-hidden="true">
          <ArrowRight size={20} />
          <span>Public TLS + authorization</span>
        </div>

        <section className="st-security-zone st-security-zone-control">
          <span className="st-security-zone-label">Control plane</span>
          <article className="primary">
            <ShieldCheck size={23} weight="fill" aria-hidden="true" />
            <div>
              <strong>API Gateway / Control API</strong>
              <small>Tenant checks · idempotency · policy</small>
            </div>
          </article>
          <article>
            <Database size={22} aria-hidden="true" />
            <div>
              <strong>PostgreSQL + RLS</strong>
              <small>Projects · versions · audit · ledger</small>
            </div>
          </article>
          <article>
            <Queue size={22} aria-hidden="true" />
            <div>
              <strong>Queue / Scheduler</strong>
              <small>Leases · retry budgets · DLQ</small>
            </div>
          </article>
          <article>
            <Key size={22} aria-hidden="true" />
            <div>
              <strong>Scoped grants</strong>
              <small>Method · key · TTL · job prefix</small>
            </div>
          </article>
        </section>

        <div className="st-security-vertical-flow" aria-hidden="true">
          <ArrowDown size={20} />
          <span>Untrusted document</span>
        </div>

        <section className="st-security-zone st-security-zone-quarantine">
          <span className="st-security-zone-label">Untrusted intake</span>
          <article>
            <CloudArrowUp size={22} aria-hidden="true" />
            <div>
              <strong>Quarantine storage</strong>
              <small>Original bytes · immutable lineage</small>
            </div>
          </article>
          <article>
            <MagnifyingGlass size={22} aria-hidden="true" />
            <div>
              <strong>Magic / Scanner / CDR</strong>
              <small>Allowlist · archive caps · fail closed</small>
            </div>
          </article>
          <article>
            <FileLock size={22} aria-hidden="true" />
            <div>
              <strong>Verified-object gate</strong>
              <small>Only admitted derivatives continue</small>
            </div>
          </article>
        </section>

        <div className="st-security-vertical-flow" aria-hidden="true">
          <ArrowDown size={20} />
          <span>Bounded job manifest</span>
        </div>

        <section className="st-security-zone st-security-zone-workers">
          <span className="st-security-zone-label">Processing isolation</span>
          <article>
            <TerminalWindow size={22} aria-hidden="true" />
            <div>
              <strong>CPU parser sandbox</strong>
              <small>Rootless · read-only · no network · caps</small>
            </div>
          </article>
          <article>
            <Wrench size={22} aria-hidden="true" />
            <div>
              <strong>GPU worker boundary</strong>
              <small>Exact revision · scoped IO · per-job scratch</small>
            </div>
          </article>
          <article className="external">
            <ShieldWarning size={22} weight="fill" aria-hidden="true" />
            <div>
              <strong>External Precision provider</strong>
              <small>Off by default · explicit consent · allowlist</small>
            </div>
          </article>
        </section>

        <div className="st-security-vertical-flow" aria-hidden="true">
          <ArrowDown size={20} />
          <span>Signed result manifest</span>
        </div>

        <section className="st-security-zone st-security-zone-data">
          <span className="st-security-zone-label">Verified data plane</span>
          <article>
            <HardDrives size={22} aria-hidden="true" />
            <div>
              <strong>Derived object storage</strong>
              <small>Source maps · exports · version lineage</small>
            </div>
          </article>
          <article>
            <LockKey size={22} aria-hidden="true" />
            <div>
              <strong>Evidence validator</strong>
              <small>Accepted blocks and claims remain source-bound</small>
            </div>
          </article>
          <article>
            <FileLock size={22} aria-hidden="true" />
            <div>
              <strong>Export boundary</strong>
              <small>Authorized download · expiry · audit event</small>
            </div>
          </article>
        </section>

        <aside className="st-security-side-system st-security-admin">
          <span>Privileged boundary</span>
          <strong>Admin / Support access</strong>
          <small>Least privilege · step-up · reason · immutable audit</small>
        </aside>
        <aside className="st-security-side-system st-security-observability">
          <span>Operational boundary</span>
          <strong>Metrics / Traces / Logs</strong>
          <small>
            Allowlisted fields · no document content · alert delivery
          </small>
        </aside>
        <aside className="st-security-side-system st-security-supply">
          <span>Supply-chain boundary</span>
          <strong>CI / Images / Models</strong>
          <small>SHA · SBOM · license snapshot · signature · self-test</small>
        </aside>
      </div>

      <div className="st-security-accessible-flow">
        <h3>Accessible trust-boundary sequence</h3>
        <ol>
          <li>
            Browser authenticates through the public TLS and identity boundary.
          </li>
          <li>
            The control API authorizes tenant, project, object, and requested
            policy.
          </li>
          <li>
            Original bytes enter quarantine and cannot reach parsers before
            validation.
          </li>
          <li>
            CPU and GPU workers receive bounded job manifests and scoped object
            grants.
          </li>
          <li>
            Optional external processing is disabled unless policy and consent
            both allow it.
          </li>
          <li>
            Accepted results require a signed manifest and evidence validation.
          </li>
          <li>
            Exports, retention changes, deletion, and privileged access create
            audit events.
          </li>
        </ol>
      </div>

      <div className="st-security-control-table-wrap">
        <table className="st-security-control-table">
          <caption>Threat-to-control evidence register</caption>
          <thead>
            <tr>
              <th>Threat</th>
              <th>Required control</th>
              <th>Current evidence boundary</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {controls.map((item) => (
              <tr key={item.threat}>
                <th scope="row">{item.threat}</th>
                <td>{item.control}</td>
                <td>{item.evidence}</td>
                <td>
                  <span data-status={item.status}>
                    {item.status === "implemented"
                      ? "Local verified"
                      : "Production evidence required"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer>
        <p>
          Production security approval still requires deployed OIDC/RLS
          evidence, scanner and sandbox attestation, cross-tenant testing,
          penetration testing, secret rotation, restore/deletion drills, and
          independent review for the exact release commit.
        </p>
        <div>
          <Link href="/legal/privacy">Privacy boundary</Link>
          <Link href="/company/contact">Request security package</Link>
        </div>
      </footer>
    </section>
  );
}
