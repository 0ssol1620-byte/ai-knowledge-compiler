# Native spent development arm — 2026-09-09

This is offline development evidence, not production qualification, a fresh holdout,
or a public superiority result. The full Native arm now retains all 1,403 eligible
olmOCR source pages in the existing spent Arena manifest. No new model/GPU calls
were made. The earlier limited pilots and negative selector result remain intact.

## Capture and evaluation

`capture_spent.py --all-units --output-name native-spent-full-20260909` seals the
source manifest and parser/projection/capture bytes before parsing. Its runtime never
loads hidden rule labels. An isolated second process, `score_native.py`, validates
the sealed capture and calls the pinned official evaluator's rule objects directly.
This avoids its CLI's POSIX filename matching on Windows; it does not replace rules.

| Native outcome | Pages |
|---|---:|
| Text observed | 1,178 |
| Text unobserved | 173 |
| Runtime unqualified | 49 |
| Parser failed | 3 |
| Total retained | 1,403 |

All 8,413 official rules, including the evaluator's baseline bucket, are retained.
Failed/unqualified parser executions fail all their rules, including absence rules.
The mean of per-JSONL pass rates including baseline is **0.19414160497664207**.
This is a score for this Native text projection, not character accuracy or information
retention. Math buckets pass 0 rules; the table bucket passes 1/1,022. Native text
availability is therefore insufficient evidence to accept structured content.
SCLR, verified production latency and cost remain unmeasured.

The final run has zero evaluator exceptions. The earlier run is preserved as
`EVALUATOR_INCOMPLETE` (9 Windows console UnicodeEncodeError cases); it is not an
accepted receipt. The rerun uses identical capture/scorer/rules with UTF-8 stdout and
an isolated equation cache. No thresholds, source outputs or expected results changed.

The three parser failures reproduce as one pypdf decompression limit and two image
colorspace KeyErrors. One sampled runtime-unqualified page needs `jbig2dec`; this
does not establish the cause for all 49. Limits were not weakened to make rows pass.

## Bound evidence

Local capture: `D:/trouter-0909/.chatgpt2codex/native-spent-full-20260909/`.
Accepted scoring: `D:/trouter-0909/.chatgpt2codex/native-spent-score-utf8-20260909/`.
Raw source/text/rule output stays local; this document does not redistribute the corpus.

- Source manifest: `sha256:2ec00f371db5069216362ee946b084ed0d222474162d7eadcbf717f09ae55e7c`
- Capture freeze: `sha256:b91063cd47ebefdd8f14d87df21f7c86ade6f4c0755872d6584819d99dcbd2ff`
- Observations: `sha256:ac4b4e669eb4b2d09913b77dd0420d779866f4adc00edc69e799cd85c39512a8`
- Scorer: `sha256:da04858e7ba42a007472dcf9ecf57f690ccd32b02bae8552892fda27c8aadc48`
- Rule results: `sha256:630850ad4cd953e324929778263e1419ad6b536a0f48cb4088e54fd6e084fc4b`
- Official evaluator checkout: `cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c`

Capture runtime: Windows/Python 3.12.13, pypdf 6.15.0, pydantic 2.13.4.
Scoring uses the separate `olmocr-eval-venv`, hash-locked dependencies and local
`olmocr-eval-browsers`; its FREEZE records dependency versions and evaluator/rule hashes.
Use `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, and that browser directory when reproducing.
Outputs must be new scratch directories; overwriting sealed evidence is refused.

Validation: 15 capture/binding tests, 65 focused Native/router execution regressions,
and Ruff pass. Six capture/parser/projection/scorer/data/result hash bindings were
rechecked after scoring. No production policy, queue, model or customer gate changed.

## Next decision

Bind this arm into a common-denominator replay of fixed, Native, current router,
recovery and always-all policies. Historical model runs use other environments;
the Native-only score alone is not a fair newly measured head-to-head comparison.
Evaluate loss, unresolved output, regret and verified costs before deciding whether
the routing complexity adds value. Do not open fresh holdout or claim superiority
from this result.
