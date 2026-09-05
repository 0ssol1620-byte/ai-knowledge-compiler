# arena.tavonel — lane E1

TAVONEL system variants replayed over the frozen model outputs
(masterplan §23–27, ARENA_CONTRACT §3.5, §3.6, §8).

```
python -m arena.tavonel signals        [--model KEY]...        # tavonel/signals/<model>/<case>.json
python -m arena.tavonel disagreement   [--model KEY]...        # tavonel/disagreement/pairs.jsonl
python -m arena.tavonel disagreement   --correlate             # AFTER scoring only
python -m arena.tavonel freeze-routes  --variant A|B|C|D|E     # tavonel/route_decisions/<variant>/
python -m arena.tavonel replay         --variant ...           # tavonel/adaptive_replay/<variant>/
python -m arena.tavonel plan-recovery  --variant ...           # tavonel/recovery_jobs/
python -m arena.tavonel cost           --variant ...           # tavonel/cost/<variant>.json
```

Every command takes `--root` (default: the namespace root). Nothing here calls
a provider, spends money or runs inference, so there is no `--execute` gate;
what this lane guards is the *order*, not the wallet.

## Order (masterplan §2.2)

```
signals -> disagreement -> freeze-routes -> replay -> plan-recovery -> cost
                                 |
                                 +-- refuses to run once scores/<primary>/ exists
```

`freeze-routes` writes `FROZEN.json` with a hash over every decision, and
refuses to overwrite one. `replay` re-verifies that hash before it copies
anything. Variant E inverts the rule: it *requires* scores, is labelled
`ORACLE_POST_HOC_NOT_DEPLOYABLE` in its directory name and in every record, and
is a ceiling rather than a system.

## Variants (masterplan §25)

| id | what it does | model calls |
|---|---|---|
| `A_base` | primary only | 1 |
| `B_recovery` | primary output + a recovery plan for tripped pages | 1 (+ recovery jobs) |
| `C_adaptive` | primary, then a specialist on a named trigger | 1–2 |
| `D_opus_escalation` | C, plus Opus for the riskiest pages inside a cap | 1–3 |
| `E_oracle` | best officially scored output per page — not deployable | all |

Default slots (MP §13.1, §25): primary `paddleocr_vl_1_6`, text specialist
`deepseek_ocr2`, table/layout specialist `mineru_vlm`, formula specialist
`infinity_parser2_pro`, escalation `opus5_subscription`. All are parameters;
`--primary` and `--set-threshold NAME=VALUE` override them and change the
`policy_sha256` that the frozen decisions record.

## Three rules this lane will not bend

1. **No threshold here is calibrated.** Every one carries `calibrated: false`
   and a rationale. They order pages; they do not measure quality.
2. **No blended quality score decides acceptance.** The 2026-08 campaign
   published blind ranking as *not supported*; triggers are named and separate,
   and the risk score is used only to rank pages for escalation.
3. **A number that cannot be computed is `null` with a reason.** Unpriced
   pages, missing geometry, unexecuted recovery and blocked evaluators are
   never zero.

Tests: `.venv/Scripts/python.exe -m pytest research/model_arena_20260903/tests/tavonel -q`
