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
import diagnostics from "@/data/benchmark-diagnostics.json";

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
            Compare parser fidelity, runtime, cost, and repeat stability on the
            same isolated corpus and evaluator.
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
              No reproducibility metrics are ready for publication.
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
            <h2 id="benchmark-results-title">Measured parser evidence</h2>
            <p>
              Official demo subset, three blind repeats. Derived 1−edit values
              are presentation companions, not renamed leaderboard metrics.
            </p>
          </div>
          <span>Evaluator {snapshot.evaluator_version}</span>
        </div>
        <div className="benchmark-table-frame">
          <table>
            <caption className="sr-only">
              Reproducible parser results on the same corpus
            </caption>
            <thead>
              <tr>
                <th scope="col">Candidate</th>
                <th scope="col">Status</th>
                <th scope="col">Text 1−edit</th>
                <th scope="col">Formula 1−edit</th>
                <th scope="col">Table TEDS</th>
                <th scope="col">Structure TEDS</th>
                <th scope="col">Table 1−edit</th>
                <th scope="col">Reading order 1−edit</th>
                <th scope="col">Mean runtime</th>
                <th scope="col">Cost per page</th>
                <th scope="col">Exact repeats</th>
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
                  <td>{formatBenchmarkPercent(dataset.metrics.text_edit_companion)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.formula_edit_companion)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.table_teds)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.table_structure_teds)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.table_edit_companion)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.reading_order_companion)}</td>
                  <td>
                    {formatBenchmarkLatency(dataset.metrics.mean_latency_ms)}
                  </td>
                  <td>
                    {formatBenchmarkCost(dataset.metrics.cost_per_page_usd)}
                  </td>
                  <td>{formatBenchmarkPercent(dataset.metrics.exact_repeat_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section
        className="benchmark-diagnostics"
        aria-labelledby="benchmark-diagnostics-title"
      >
        <div>
          <span>Diagnostic lane · excluded from measured ranking</span>
          <h2 id="benchmark-diagnostics-title">Failures stay visible.</h2>
          <p>
            A model enters the measured table only after inference and three
            complete repeats. Pre-inference failures retain their frozen
            revision and evidence, without borrowing vendor scores.
          </p>
        </div>
        {diagnostics.diagnostics.map((diagnostic) => (
          <article key={diagnostic.id}>
            <header>
              <div>
                <strong>{diagnostic.label}</strong>
                <span>{diagnostic.status}</span>
              </div>
              <b>{diagnostic.completed_inference_cases} scored cases</b>
            </header>
            <p>{diagnostic.summary}</p>
            <dl>
              <div><dt>Failure class</dt><dd>{diagnostic.failure_class}</dd></div>
              <div><dt>Model revision</dt><dd><code>{diagnostic.model_revision.slice(0, 12)}</code></dd></div>
              <div><dt>Artifact</dt><dd><code>{diagnostic.artifact_manifest_sha256.slice(0, 19)}…</code></dd></div>
              <div><dt>Diagnostic evidence</dt><dd><code>{diagnostic.diagnostic_evidence_sha256.slice(0, 19)}…</code></dd></div>
              <div><dt>Next gate</dt><dd>{diagnostic.next_gate}</dd></div>
            </dl>
          </article>
        ))}
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
              Text, formulas, tables, reading order, repeat stability, and failures
            </dd>
          </div>
          <div>
            <dt>Execution</dt>
            <dd>
              Model revision, artifact hash, GPU, service shape, and three repeats
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
          This release uses the Apache-2.0 OmniDocBench official demo subset.
          Ground truth was absent from inference workers and introduced only in
          the separately hashed evaluator lane. It is not a full leaderboard run.
        </p>
      </section>
    </Wrapper>
  );
}
