# research/tavonel_eval_v2

The v2 research namespace for the paper programme described in
`TAVONEL_PAPER_RESEARCH_EXECUTION_MASTER_HANDOFF_2026-08-21_KO.md`.

Everything this programme produces lives under this directory. Nothing outside
it is created or modified. The pre-existing sealed evidence under
`docs/evidence/`, `docs/ip/` and `research/experiments/` is read-only here and
is never re-sealed, repaired or superseded by anything in this tree.

## Standing constraints

- **IP gate is CLOSED.** No Korean Intellectual Property Office filing
  acknowledgement exists under `docs/ip/receipts/`; the receipts there are
  package-build and self-test receipts for the submission bundle, which are not
  a filing receipt. No paper, arXiv upload, public repository, benchmark or data
  release while it stays closed. Private local research and evidence generation
  continue.
- **GPU spend is $0 and unapproved.** Nothing here touches a GPU or a paid API.
  The first step that needs one stops and asks with the evidence attached.

## Layout

    protocols/       frozen protocol documents
    tools/           verification, freezing and the run driver
    acquisition/     source-family adapters and the declared input lists
    canonicalization/ raw bytes -> canonical document, run once, ahead of both builds
    compiler/        the SELECTIVE build (uses akc_cir)
    oracle/          the INDEPENDENT full rebuild (standard library only)
    comparator/      state comparison; imports neither build path
    tests/           regression tests, including reproductions of open findings
    receipts/        machine-readable receipts, each self-hashed
    artifacts/       development | sealed_validation | untouched_confirmatory
    incident_ledger.md   append-only; open findings and their evidence

## The independence rule

The point of the oracle is to remove circular validation, so the separation is
enforced and evidenced rather than asserted:

| requirement | how it is held | where the evidence is |
|---|---|---|
| separate executable | `oracle/independent_full_build.py` stands alone | `static_independence.oracle.sha256` |
| stdlib only | AST scan of its imports | `static_independence.oracle.non_stdlib_imports` |
| separate process | launched by `subprocess`; pids compared | `records[].distinct_processes` |
| unreachable, not merely unimported | child runs `python -I -S`, which drops the editable install that otherwise puts `packages/cir-python/src` back on `sys.path` | `records[].oracle_cir_python_on_path` |
| runtime guard | `sys.meta_path` finder refuses `akc_cir`; probed each run | `runtime_guard_probe` |
| no plan, cache or prior state | its only argument is the AFTER canonical document | `oracle.independence.argv` |
| disjoint outputs | `artifacts/<split>/{selective,oracle,comparison}` | `output_roots_disjoint` |
| independent comparator | `comparator/compare_states.py` imports neither side | `static_independence.comparator` |
| forensics on failure | both states, both streams, per-artifact diff | `artifacts/<split>/forensic/<pair_id>/` |

## Running P0

    python research/tavonel_eval_v2/tools/verify_sealed_evidence.py
    python research/tavonel_eval_v2/tools/freeze_protocol.py
    python research/tavonel_eval_v2/acquisition/fetch_corpus.py
    python research/tavonel_eval_v2/canonicalization/canonicalize.py
    python research/tavonel_eval_v2/tools/run_p1_smoke.py
    python -m pytest research/tavonel_eval_v2/tests -q

Acquisition reads the network. Everything else is offline.

## Open findings

See `incident_ledger.md`. Two are open, and neither has been worked around:

- **INC-V2-001** — four sealed bindings and two receipt self-hashes no longer
  verify, with no superseding receipt. Founder decision required.
- **INC-V2-002** — a case-only edit escapes invalidation and leaves a stale
  artifact, because the change detector normalises text more coarsely than the
  artifact payload stores it. `G_P0_EQUIVALENCE` fails on it, deliberately.
