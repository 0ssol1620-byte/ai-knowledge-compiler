import { claimFigure } from "@/lib/claims";

/**
 * The counterfactual — handoff item 3, and the one it calls the strongest
 * result on the page.
 *
 * It earns that description because it is the only figure here that isolates a
 * cause. An accuracy number says how well the system did; this says what one
 * part of it was worth, by running the same corpus through the same model with
 * the same evaluator and removing only the recovery lane's output. 80.6 becomes
 * 53.7.
 *
 * The single-variable framing is not decoration, and the pack requires it:
 * "model, evaluator revision, corpus and configuration fixed, with only the
 * recovery artefacts removed". Without that sentence the pair of numbers is
 * just two scores.
 *
 * Three benchmarks agree, which is why all three are shown rather than the
 * most flattering one. OmniDocBench needs its own note because its metrics run
 * in opposite directions: edit distance is better lower, TEDS better higher.
 */

interface OlmocrRecovery {
  benchmark: string;
  with_recovery: number;
  without_recovery: number;
  with_recovery_ci95: [number, number];
  without_recovery_ci95: [number, number];
  rule_failures_with: number;
  rule_failures_without: number;
}

interface ParsebenchRecovery {
  rule_failures_with: number;
  rule_failures_without: number;
  content_faithfulness_with: number;
  content_faithfulness_without: number;
  table_grits_with: number;
  table_grits_without: number;
}

interface OmnidocRecovery {
  text_edit_distance_with: number;
  text_edit_distance_without: number;
  reading_order_with: number;
  reading_order_without: number;
  table_teds_with: number;
  table_teds_without: number;
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

export function RecoverySection() {
  const olmocr = claimFigure<OlmocrRecovery>("recovery-contribution-olmocr");
  const parse = claimFigure<ParsebenchRecovery>(
    "recovery-contribution-parsebench",
  );
  const omni = claimFigure<OmnidocRecovery>(
    "recovery-contribution-omnidocbench",
  );
  const o = olmocr.numbers;

  return (
    <section className="tv-recovery" id="recovery">
      <div className="tv-recovery-head">
        <p className="tv-recovery-eyebrow">One variable changed</p>
        <h2>What the recovery lane is worth.</h2>
        <p className="tv-recovery-lead">
          The same corpus, the same model, the same evaluator. The only
          difference between these two runs is whether the recovery lane&rsquo;s
          output was kept.
        </p>
      </div>

      <div className="tv-recovery-pair">
        <div className="tv-recovery-arm" data-arm="with">
          <span>With recovery</span>
          <strong>{o.with_recovery}</strong>
          <small>
            95% CI {o.with_recovery_ci95[0]}–{o.with_recovery_ci95[1]} ·{" "}
            {o.rule_failures_with.toLocaleString("en-US")} rule failures
          </small>
        </div>
        <div className="tv-recovery-arm" data-arm="without">
          <span>Recovery disabled</span>
          <strong>{o.without_recovery}</strong>
          <small>
            95% CI {o.without_recovery_ci95[0]}–{o.without_recovery_ci95[1]} ·{" "}
            {o.rule_failures_without.toLocaleString("en-US")} rule failures
          </small>
        </div>
      </div>

      {/* The pack's must_say. Without it the pair is two numbers, not a cause. */}
      <div className="tv-recovery-context">
        {olmocr.context.map((sentence) => (
          <p key={sentence.text} lang={sentence.lang}>
            {sentence.text}
          </p>
        ))}
      </div>

      <div className="tv-recovery-corroboration">
        <h3>The other two benchmarks agree</h3>
        <dl>
          <div>
            <dt>ParseBench · rule failures</dt>
            <dd>
              {parse.numbers.rule_failures_with.toLocaleString("en-US")} →{" "}
              <b>{parse.numbers.rule_failures_without.toLocaleString("en-US")}</b>
            </dd>
          </div>
          <div>
            <dt>ParseBench · table structure (GriTS)</dt>
            <dd>
              {pct(parse.numbers.table_grits_with)} →{" "}
              <b>{pct(parse.numbers.table_grits_without)}</b>
            </dd>
          </div>
          <div>
            <dt>OmniDocBench · table structure (TEDS)</dt>
            <dd>
              {pct(omni.numbers.table_teds_with)} →{" "}
              <b>{pct(omni.numbers.table_teds_without)}</b>
            </dd>
          </div>
          <div>
            <dt>OmniDocBench · text edit distance</dt>
            <dd>
              {omni.numbers.text_edit_distance_with} →{" "}
              <b>{omni.numbers.text_edit_distance_without}</b>
            </dd>
          </div>
        </dl>
        {/* OmniDocBench's must_say: its two metrics point opposite ways. */}
        {omni.context.map((sentence) => (
          <p
            key={sentence.text}
            lang={sentence.lang}
            className="tv-recovery-direction"
          >
            {sentence.text}
          </p>
        ))}
      </div>
    </section>
  );
}
