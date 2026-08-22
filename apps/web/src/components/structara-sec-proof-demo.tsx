"use client";

import {
  ArrowSquareOut,
  CheckCircle,
  FileCode,
  Graph,
  LinkSimple,
  ShieldWarning,
  StackSimple,
  Table,
} from "@phosphor-icons/react";
import { useState } from "react";

import { SEC_PUBLIC_FIXTURE } from "@/lib/sec-public-fixture";

type SecProofTab = "Original" | "Markdown" | "Vault" | "Graph" | "Proof";

const tabs = [
  { id: "Original", icon: Table },
  { id: "Markdown", icon: FileCode },
  { id: "Vault", icon: StackSimple },
  { id: "Graph", icon: Graph },
  { id: "Proof", icon: LinkSimple },
] as const;

export function StructaraSecProofDemo() {
  const [tab, setTab] = useState<SecProofTab>("Original");
  const [selectedFactId, setSelectedFactId] = useState(
    "fact-total-net-sales-2025",
  );
  const selectedFact =
    SEC_PUBLIC_FIXTURE.facts.find((fact) => fact.id === selectedFactId) ??
    SEC_PUBLIC_FIXTURE.facts[0];

  return (
    <section className="st-sec-proof" aria-labelledby="sec-proof-title">
      <header className="st-sec-proof-header">
        <div>
          <p className="st-context-label">Official SEC public source</p>
          <h2 id="sec-proof-title">
            Apple 2025 Form 10-K, compiled without losing the filing.
          </h2>
          <p>
            Every displayed fact below is tied to SEC accession{" "}
            {SEC_PUBLIC_FIXTURE.source.accession}. This is product evidence from
            a public filing—not a benchmark score, investment recommendation, or
            claim about extraction quality.
          </p>
        </div>
        <dl className="st-sec-source-summary">
          <div>
            <dt>Form</dt>
            <dd>{SEC_PUBLIC_FIXTURE.source.form}</dd>
          </div>
          <div>
            <dt>Period</dt>
            <dd>{SEC_PUBLIC_FIXTURE.source.reportPeriod}</dd>
          </div>
          <div>
            <dt>CIK</dt>
            <dd>{SEC_PUBLIC_FIXTURE.source.cik}</dd>
          </div>
          <div>
            <dt>Filed</dt>
            <dd>{SEC_PUBLIC_FIXTURE.source.filingDate}</dd>
          </div>
        </dl>
      </header>

      <nav
        className="st-sec-proof-tabs"
        aria-label="SEC proof transformation views"
      >
        {tabs.map(({ id, icon: Icon }) => (
          <button
            type="button"
            aria-pressed={tab === id}
            className={tab === id ? "active" : undefined}
            onClick={() => setTab(id)}
            key={id}
          >
            <Icon size={15} aria-hidden="true" />
            {id}
          </button>
        ))}
      </nav>

      <div className="st-sec-proof-workspace">
        <section
          className="st-sec-proof-main"
          aria-label="Filing evidence workspace"
        >
          {tab === "Original" && (
            <OriginalTable
              selectedFactId={selectedFactId}
              onSelectFact={setSelectedFactId}
            />
          )}
          {tab === "Markdown" && (
            <section className="st-sec-markdown" aria-label="Compiled Markdown">
              <header>
                <span>Compiled layer</span>
                <strong>apple-2025-revenue-evidence.md</strong>
              </header>
              <pre>{SEC_PUBLIC_FIXTURE.markdown}</pre>
            </section>
          )}
          {tab === "Vault" && <VaultView />}
          {tab === "Graph" && <GraphView />}
          {tab === "Proof" && <ProofLedger selectedFact={selectedFact} />}
        </section>

        <aside className="st-sec-fact-inspector" aria-live="polite">
          <header>
            <span>Selected evidence</span>
            <strong>{selectedFact.label}</strong>
            <small>
              {selectedFact.period} · {selectedFact.unit}
            </small>
          </header>
          <div className="st-sec-selected-value">
            <strong>${selectedFact.valueMillions.toLocaleString()}</strong>
            <span>million</span>
          </div>
          <dl>
            <div>
              <dt>Source row</dt>
              <dd>{selectedFact.sourceRow}</dd>
            </div>
            <div>
              <dt>Source column</dt>
              <dd>{selectedFact.sourceColumn}</dd>
            </div>
            <div>
              <dt>Accession</dt>
              <dd>{SEC_PUBLIC_FIXTURE.source.accession}</dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>{SEC_PUBLIC_FIXTURE.source.sourceLocation}</dd>
            </div>
          </dl>
          <a
            className="st-sec-source-link"
            href={SEC_PUBLIC_FIXTURE.source.archiveUrl}
            target="_blank"
            rel="noreferrer"
          >
            Open official filing
            <ArrowSquareOut size={14} aria-hidden="true" />
          </a>
          <div className="st-sec-proof-caveat">
            <ShieldWarning size={15} weight="fill" aria-hidden="true" />
            <p>
              Archive SHA-256 is pending controlled byte retrieval. The product
              shows that gap instead of inventing a checksum.
            </p>
          </div>
        </aside>
      </div>

      <footer className="st-sec-proof-footer">
        <span>
          <CheckCircle size={15} weight="fill" aria-hidden="true" />
          Source authority, accession, filing date, report period, table
          location, unit, row, and column are registered.
        </span>
        <a
          href={SEC_PUBLIC_FIXTURE.source.filingIndexUrl}
          target="_blank"
          rel="noreferrer"
        >
          Filing index
          <ArrowSquareOut size={13} aria-hidden="true" />
        </a>
      </footer>
    </section>
  );
}

function OriginalTable({
  selectedFactId,
  onSelectFact,
}: {
  selectedFactId: string;
  onSelectFact: (factId: string) => void;
}) {
  const factByCell = new Map(
    SEC_PUBLIC_FIXTURE.facts.map((fact) => [
      `${fact.sourceRow}:${fact.sourceColumn}`,
      fact,
    ]),
  );

  return (
    <section className="st-sec-original" aria-label="Original SEC filing table">
      <header>
        <div>
          <span>Original source reconstruction</span>
          <strong>Products and Services Performance</strong>
        </div>
        <small>Dollars in millions · Form 10-K page 22</small>
      </header>
      <div className="st-sec-filing-paper">
        <p>Apple Inc. | 2025 Form 10-K | 22</p>
        <h3>Products and Services Performance</h3>
        <p>
          The following table shows net sales by category for 2025, 2024 and
          2023 (dollars in millions):
        </p>
        <div className="st-sec-table-scroll">
          <table>
            <caption>Apple net sales by product category</caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">2025</th>
                <th scope="col">2024</th>
                <th scope="col">2023</th>
              </tr>
            </thead>
            <tbody>
              {SEC_PUBLIC_FIXTURE.productCategories.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  {row.values.map((value, index) => {
                    const period = String(2025 - index);
                    const fact = factByCell.get(`${row.label}:${period}`);
                    return (
                      <td
                        key={period}
                        data-selected={fact?.id === selectedFactId}
                        data-evidence={Boolean(fact)}
                      >
                        {fact ? (
                          <button
                            type="button"
                            aria-pressed={fact.id === selectedFactId}
                            onClick={() => onSelectFact(fact.id)}
                          >
                            ${value.toLocaleString()}
                          </button>
                        ) : (
                          value.toLocaleString()
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function VaultView() {
  return (
    <section className="st-sec-vault" aria-label="Compiled knowledge Vault">
      <header>
        <span>Portable knowledge package</span>
        <strong>Apple 2025 filing Vault</strong>
      </header>
      <div className="st-sec-vault-grid">
        {SEC_PUBLIC_FIXTURE.notes.map((note) => (
          <article key={note.id}>
            <span>{note.type}</span>
            <h3>{note.title}</h3>
            <ul>
              {note.properties.map((property) => (
                <li key={property}>{property}</li>
              ))}
            </ul>
            <footer>
              <ShieldWarning size={13} aria-hidden="true" />
              {note.evidence.length} evidence reference(s)
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}

function GraphView() {
  return (
    <section
      className="st-sec-graph"
      aria-label="Accessible SEC knowledge graph"
    >
      <header>
        <span>Evidence-bound relation graph</span>
        <strong>Filing → Entity → Metric</strong>
      </header>
      <div className="st-sec-graph-stage" aria-hidden="true">
        <div className="st-sec-graph-node filing">Apple 2025 10-K</div>
        <div className="st-sec-graph-node entity">Apple Inc.</div>
        <div className="st-sec-graph-node metric">Total net sales</div>
        <div className="st-sec-graph-node service">Services net sales</div>
        <span className="st-sec-edge edge-a">filed_by</span>
        <span className="st-sec-edge edge-b">reports</span>
        <span className="st-sec-edge edge-c">includes</span>
      </div>
      <table className="st-sec-graph-table">
        <caption>Accessible relation list</caption>
        <thead>
          <tr>
            <th>Subject</th>
            <th>Predicate</th>
            <th>Object</th>
          </tr>
        </thead>
        <tbody>
          {SEC_PUBLIC_FIXTURE.relations.map((relation) => (
            <tr
              key={`${relation.subject}-${relation.predicate}-${relation.object}`}
            >
              <td>{relation.subject}</td>
              <td>
                <code>{relation.predicate}</code>
              </td>
              <td>{relation.object}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ProofLedger({
  selectedFact,
}: {
  selectedFact: (typeof SEC_PUBLIC_FIXTURE.facts)[number];
}) {
  return (
    <section
      className="st-sec-ledger"
      aria-label="SEC source provenance ledger"
    >
      <header>
        <span>Proof receipt</span>
        <strong>
          {selectedFact.label} · {selectedFact.period}
        </strong>
      </header>
      <div className="st-sec-proof-chain">
        {[
          ["Source authority", SEC_PUBLIC_FIXTURE.source.authority],
          [
            "Entity / CIK",
            `${SEC_PUBLIC_FIXTURE.source.entity} / ${SEC_PUBLIC_FIXTURE.source.cik}`,
          ],
          [
            "Filing",
            `${SEC_PUBLIC_FIXTURE.source.form} · ${SEC_PUBLIC_FIXTURE.source.accession}`,
          ],
          ["Period", SEC_PUBLIC_FIXTURE.source.reportPeriod],
          ["Location", SEC_PUBLIC_FIXTURE.source.sourceLocation],
          [
            "Fact cell",
            `${selectedFact.sourceRow} / ${selectedFact.sourceColumn}`,
          ],
          ["Value", `$${selectedFact.valueMillions.toLocaleString()} million`],
          ["Archive checksum", SEC_PUBLIC_FIXTURE.source.archiveSha256Status],
        ].map(([label, value], index) => (
          <div key={label} data-complete={index < 7}>
            <i>
              {index < 7 ? (
                <CheckCircle size={15} weight="fill" />
              ) : (
                <ShieldWarning size={15} weight="fill" />
              )}
            </i>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
