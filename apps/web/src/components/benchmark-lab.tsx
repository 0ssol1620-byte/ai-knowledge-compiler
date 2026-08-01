import {
  CheckCircle,
  Database,
  Gauge,
  LockKey,
  MagnifyingGlass,
} from "@phosphor-icons/react/dist/ssr";

import {
  formatBenchmarkCost,
  formatBenchmarkLatency,
  formatBenchmarkPercent,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";

const statusLabel = {
  available: "Verified",
  source_adapter_ready: "Source adapter verified",
  evidence_required: "Corpus required",
} as const;

export function BenchmarkLab({ embedded = false }: { embedded?: boolean }) {
  const snapshot = publicBenchmarkSnapshot;
  const isAvailable = snapshot.status === "available";
  const Wrapper = embedded ? "section" : "main";
  const Heading = embedded ? "h2" : "h1";

  return (
    <Wrapper
      className="simple-page benchmark-lab-page"
      id={embedded ? undefined : "main-content"}
      data-embedded={embedded}
      aria-label={embedded ? "Public benchmark evidence" : undefined}
    >
      <header className="benchmark-lab-heading">
        <div>
          <Heading>Benchmark Lab</Heading>
          <p>
            Compare text, number, table, and provenance accuracy alongside
            latency and per-page cost using the same corpus and evaluator.
          </p>
        </div>
        <span className="benchmark-release-state" data-ready={isAvailable}>
          {isAvailable ? (
            <CheckCircle size={17} weight="fill" aria-hidden="true" />
          ) : (
            <LockKey size={17} aria-hidden="true" />
          )}
          {isAvailable
            ? "Publishable evidence bundle"
            : "Public metrics locked"}
        </span>
      </header>

      {!isAvailable && (
        <section
          className="benchmark-evidence-notice"
          aria-labelledby="benchmark-evidence-title"
        >
          <MagnifyingGlass size={22} aria-hidden="true" />
          <div>
            <h2 id="benchmark-evidence-title">
              No performance metrics are ready for publication.
            </h2>
            <p>
              The DART adapter and evaluation contract are ready. Metrics remain
              unavailable until a rights-cleared golden corpus, independent
              label review, real model and hardware runs, and an approved
              evidence bundle exist.
            </p>
          </div>
        </section>
      )}

      <section
        className="benchmark-results-region"
        aria-labelledby="benchmark-results-title"
      >
        <div className="benchmark-results-heading">
          <div>
            <h2 id="benchmark-results-title">Results by document type</h2>
            <p>Unmeasured cells remain “Not measured.”</p>
          </div>
          <span>Evaluator {snapshot.evaluator_version}</span>
        </div>
        <div className="benchmark-table-frame">
          <table>
            <caption className="sr-only">
              Publishable benchmark results by document type
            </caption>
            <thead>
              <tr>
                <th scope="col">Document type</th>
                <th scope="col">Status</th>
                <th scope="col">Text</th>
                <th scope="col">Numbers</th>
                <th scope="col">Tables</th>
                <th scope="col">Provenance</th>
                <th scope="col">p95 latency</th>
                <th scope="col">Cost per page</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.datasets.map((dataset) => (
                <tr key={dataset.id}>
                  <th scope="row">
                    <strong>{dataset.label}</strong>
                    <span>{dataset.source}</span>
                  </th>
                  <td>
                    <span className={`benchmark-status ${dataset.status}`}>
                      {statusLabel[dataset.status]}
                    </span>
                  </td>
                  <td>{formatBenchmarkPercent(dataset.metrics.text)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.numbers)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.tables)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.provenance)}</td>
                  <td>
                    {formatBenchmarkLatency(dataset.metrics.p95_latency_ms)}
                  </td>
                  <td>
                    {formatBenchmarkCost(dataset.metrics.cost_per_page_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section
        className="benchmark-methodology"
        aria-labelledby="benchmark-method-title"
      >
        <div className="benchmark-method-intro">
          <Gauge size={22} aria-hidden="true" />
          <div>
            <h2 id="benchmark-method-title">What is fixed before the score</h2>
            <p>
              A single average never hides failure cases. Each result bundles
              the corpus, evaluator, model, runtime environment, and raw
              failures.
            </p>
          </div>
        </div>
        <dl>
          <div>
            <dt>Corpus</dt>
            <dd>
              Rights clearance, split hashes, holdout isolation, label review
            </dd>
          </div>
          <div>
            <dt>Evaluation</dt>
            <dd>
              Text, numbers, tables, formulas, reading order, and provenance
            </dd>
          </div>
          <div>
            <dt>Execution</dt>
            <dd>
              Model revision, image digest, GPU, and cold/warm repetitions
            </dd>
          </div>
          <div>
            <dt>Publication</dt>
            <dd>
              Raw failures, evidence bundle SHA-256, and approval record
              required
            </dd>
          </div>
        </dl>
      </section>

      <section
        className="benchmark-source-note"
        aria-label="DART data boundary"
      >
        <Database size={20} aria-hidden="true" />
        <p>
          OpenDART is used only to collect public source documents. A filing
          does not automatically become ground truth, and user or customer
          documents are never used for benchmarks.
        </p>
      </section>
    </Wrapper>
  );
}
