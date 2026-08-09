import { claimFigure, claimStatus, claimsPack, type CorpusScale } from "@/lib/claims";

/**
 * Handoff items 1 and 5, plus the space item 6 asks to be left open.
 *
 * ITEM 1 puts completion and recovery beside the corpus that produced them.
 * The pack's first hard rule is that these are not accuracy, so they sit here
 * rather than in the accuracy section, each labelled with what it measures and
 * each carrying its denominator. The recovery rate in particular is measured
 * over documents that actually failed — 1,796 of 1,797 — and stating it without
 * that denominator would read as a claim about the whole corpus.
 *
 * ITEM 5 describes the pipeline. The handoff is explicit that these stages have
 * no benchmark score and that attaching an accuracy percentage to them is
 * forbidden, so the evidence offered alongside is the structural guarantee
 * claim: reproducible architecture, zero unresolved links, no silent loss on
 * merge. Those are properties of the output, not a measure of the text.
 *
 * THE OPEN SLOT is deliberate. `quality-retry-improvement` is still being
 * measured, and the handoff asks for room to be left rather than for the page
 * to be designed around its absence. So the slot renders, says what is being
 * measured and what unblocks it, and will carry a figure when one exists. It
 * reads its own status from the pack, so the day the regenerated pack lands
 * this stops being a placeholder without anyone editing this file.
 */
export function CampaignScale() {
  const corpus = claimFigure<CorpusScale>("corpus-scale");
  const completion = claimFigure<{
    completion_fraction: number;
    planned: number;
    resolved: number;
    unresolved: number;
  }>("completion-rate");
  const recovery = claimFigure<{
    needed_recovery: number;
    recovered: number;
    rate: number;
    required_more_than_one_round: number;
  }>("recovery-rate");
  const pipeline = claimFigure<{
    stages_en: string[];
    builtin_blueprints: string[];
    export_targets: string[];
  }>("product-pipeline");
  const guarantees = claimFigure<{
    documents_exercised: number;
    blueprints: number;
    broken_links_in_output: number;
    files_lost_silently: number;
    merge_policies_tested: number;
  }>("compilation-guarantees");

  const retry = claimsPack.claims.find(
    (claim) => claim.id === "quality-retry-improvement",
  );
  const retryPending = claimStatus("quality-retry-improvement") === "withheld";

  return (
    <section className="tv-campaign" id="campaign">
      <div className="tv-campaign-head">
        <p className="tv-campaign-eyebrow">The run behind the numbers</p>
        <h2>
          {corpus.numbers.documents.toLocaleString("en-US")} documents, three
          public benchmarks.
        </h2>
      </div>

      <div className="tv-campaign-rates">
        {/*
          Two rates that are not accuracy. Labelled as what they measure, and
          each with the denominator the pack's second hard rule requires.
        */}
        <article>
          <span>Completion</span>
          <strong>
            {(completion.numbers.completion_fraction * 100).toFixed(2)}%
          </strong>
          <p>
            {completion.numbers.resolved.toLocaleString("en-US")} of{" "}
            {completion.numbers.planned.toLocaleString("en-US")} documents
            produced output. This measures whether a document finished, not
            whether the output was right.
          </p>
        </article>
        <article>
          <span>Recovery</span>
          <strong>{(recovery.numbers.rate * 100).toFixed(2)}%</strong>
          <p>
            {recovery.numbers.recovered.toLocaleString("en-US")} of{" "}
            {recovery.numbers.needed_recovery.toLocaleString("en-US")} documents
            that actually failed were recovered — the denominator is the
            failures, not the corpus.{" "}
            {recovery.numbers.required_more_than_one_round} needed more than one
            round.
          </p>
        </article>
      </div>

      <div className="tv-campaign-pipeline">
        <h3>What runs, and what it is measured on</h3>
        <ol className="tv-campaign-stages">
          {pipeline.numbers.stages_en.map((stage, index) => (
            <li key={stage}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {stage}
            </li>
          ))}
        </ol>

        {/* The pack forbids an accuracy figure on these stages. What it
            permits is the structural guarantee, so that is what is shown. */}
        <div className="tv-campaign-guarantees">
          <p className="tv-campaign-note">
            Only extraction has a public benchmark score. For the stages after
            it the evidence is structural, measured over{" "}
            {guarantees.numbers.documents_exercised.toLocaleString("en-US")}{" "}
            documents and {guarantees.numbers.blueprints} blueprints:
          </p>
          <ul>
            <li>
              <b>{guarantees.numbers.broken_links_in_output}</b> unresolved links
              in output
            </li>
            <li>
              <b>{guarantees.numbers.files_lost_silently}</b> files lost silently
              across {guarantees.numbers.merge_policies_tested} merge policies
            </li>
            <li>
              <b>{pipeline.numbers.export_targets.length}</b> export targets from
              one compiled core
            </li>
          </ul>
        </div>
      </div>

      {retryPending && retry && (
        // Reserved rather than hidden. The handoff asked for room to be left,
        // and an empty space says nothing while this says what is coming.
        <div className="tv-campaign-pending">
          <span>Still measuring</span>
          <p>
            The accuracy gain from the targeted quality retry is being measured
            now. It is not published because the retry and its no-regression
            gate have not finished, and no improvement figure goes on this page
            before it is measured.
          </p>
          {retry.unblocks_when && (
            <p className="tv-campaign-unblocks">
              Unblocks when: {retry.unblocks_when}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
