import {
  claimFigure,
  documentTypeRows,
  type BenchmarkAccuracy,
  type CorpusScale,
} from "@/lib/claims";

/**
 * What the measurements actually say — including the part that is unflattering.
 *
 * The claims pack forbids one construction by name: "presenting 80.6% as a
 * standalone headline while omitting the per-type spread". It also forbids a
 * partial table with the low-quality scan row removed. Both prohibitions point
 * at the same thing — a single average sets the wrong expectation for whoever
 * is processing degraded paper, and 36.9% is what that reader would actually
 * get.
 *
 * So the number and the table are one component. They cannot be separated by
 * editing a page, because there is no arrangement of this file in which 80.6%
 * appears without the eight rows beneath it.
 *
 * The judgement about which is the stronger asset is worth recording. The
 * honest table is. Nobody else publishes 99.0% down to 36.9%, and a reader who
 * scans degraded documents learns here rather than after paying. §1's claim is
 * that every result returns to its source; a benchmark section that hides its
 * worst row would contradict that in the same breath as asserting it.
 */
export function AccuracySection() {
  const accuracy = claimFigure<BenchmarkAccuracy>("benchmark-accuracy");
  const corpus = claimFigure<CorpusScale>("corpus-scale");
  const rows = documentTypeRows();
  const [low, high] = accuracy.numbers.confidence_interval_95;

  return (
    <section className="tv-accuracy" id="accuracy">
      <div className="tv-accuracy-head">
        <p className="tv-accuracy-eyebrow">Measured, not asserted</p>
        <h2>The number, and where it stops being true.</h2>
      </div>

      <div className="tv-accuracy-headline">
        <div className="tv-accuracy-figure">
          <strong>{accuracy.numbers.overall_percent}%</strong>
          <span>
            {accuracy.numbers.benchmark} · {""}
            {accuracy.numbers.checks_passed.toLocaleString("en-US")} of{" "}
            {accuracy.numbers.checks_total.toLocaleString("en-US")} checks
          </span>
          <span>
            95% CI {low}–{high}
          </span>
        </div>

        {/*
          The pack's must_say, rendered from the pack rather than retyped. It
          is the difference between a pass rate and a grade out of 100, and
          between "accurate" and "72.3% of documents carry at least one
          failure".
        */}
        <div className="tv-accuracy-context">
          {accuracy.context.map((sentence) => (
            <p key={sentence.text} lang={sentence.lang}>
              {sentence.text}
            </p>
          ))}
          <p className="tv-accuracy-corpus">
            Scored by the official evaluators over{" "}
            {corpus.numbers.documents.toLocaleString("en-US")} documents across{" "}
            {corpus.numbers.benchmarks.length} public benchmarks.
          </p>
        </div>
      </div>

      <div className="tv-accuracy-table">
        <h3>Accuracy by document type</h3>
        <p className="tv-accuracy-spread">
          A single average would hide a {rows[0]!.accuracy_percent}% to{" "}
          {rows.at(-1)!.accuracy_percent}% spread. Find your document below.
        </p>

        <table>
          <thead>
            <tr>
              <th scope="col">Document type</th>
              <th scope="col">Checks passed</th>
              <th scope="col">Accuracy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              // The worst row is marked rather than buried. `benchmark_slice`
              // is an evaluator filename and the pack forbids showing it, so
              // only the human label appears.
              <tr
                key={row.label_en}
                data-worst={row === rows.at(-1) || undefined}
              >
                <th scope="row">{row.label_en}</th>
                <td>
                  {row.checks_passed.toLocaleString("en-US")} /{" "}
                  {row.checks_total.toLocaleString("en-US")}
                </td>
                <td className="tv-accuracy-cell">
                  <span
                    className="tv-accuracy-bar"
                    style={{ inlineSize: `${row.accuracy_percent}%` }}
                    aria-hidden="true"
                  />
                  <b>{row.accuracy_percent}%</b>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="tv-accuracy-worst-note">
          Degraded scans are the hard case and we publish what they score.
          If that is your corpus, {rows.at(-1)!.accuracy_percent}% is the number
          to plan against, not the average above.
        </p>
      </div>

      {accuracy.evidence && (
        <p className="tv-accuracy-evidence">
          <span>Evidence</span>
          <code>{accuracy.evidence.split("/").slice(-2).join("/")}</code>
        </p>
      )}
    </section>
  );
}
