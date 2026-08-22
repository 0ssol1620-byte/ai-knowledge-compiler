# `akc_absorption` — absorption challengers, shadow only

Challenger code for the absorption experiments in
`docs/research/ABSORPTION_EXPERIMENT_CONTRACTS_BATCH1.md`. Nothing here is a
production path and nothing here is a measurement.

**This package is deliberately absent from `[tool.hatch.build.targets.wheel]`
in the root `pyproject.toml`.** It is linted, type-checked and tested with the
rest of the repository, and it does not ship. That is the structural half of
"shadow only"; the `ABSORB_*` flags in `flags.py`, all default false, are the
runtime half. Adding this package to the wheel list is a promotion decision and
requires the six gates in contract §0.5.

Protected Core (`akc_cir.{inspection,recovery_policy,reconciler,identity,`
`semantic_diff,dependency,recompilation,world_state}`) is imported and called,
never modified and never replaced. `AlignmentAwareResolver` subclasses
`LogicalIdentityResolver` from outside the core package precisely so that the
final stable-id assignment stays where contract §9.6 puts it.

## Clean room

`baseline_xversion.py` reproduces the `tech_xversion_diff` *requirements* as
stated in `docs/north-star/TAVONEL_FTO_ABSORPTION_BLUEPRINT_v1.0.md` §9.2–§9.5
and the contract's Contract A. No source of that project was read, copied,
translated or ported by the author of this module. The provenance record is
`research/experiments/EXP-0101/receipts/clean-room-provenance.json`.

## Layout

| Module | What |
|---|---|
| `flags.py` | `ABSORB_*` gates, default false |
| `element_model.py` | blueprint §9.2 typed element model |
| `assignment.py` | maximum-weight 1:1 assignment, shared by both arms |
| `alignment.py` | blueprint §9.3 compatibility signals, §9.4 candidate tiers |
| `identity_bridge.py` | supplies those signals to `akc_cir.identity` as extra signals |
| `type_reasoning.py` | blueprint §9.5 type-specific difference reasoning |
| `baseline_xversion.py` | clean-room prior-art baseline arm |
| `evolution_suite.py` | Knowledge Evolution Suite fixture (§9.7), shared with `EXP-0104` |
| `retrieval_fixture.py` | `EXP-0103` query / gold-evidence / unauthorized-probe fixture |
