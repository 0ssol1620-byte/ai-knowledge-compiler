# akc-health-scan

Local-only **Health Scan** analyzer producing the blueprint §5.2 outputs.
Every finding carries `"label": "heuristic"`; the scanner performs **no
network/cloud calls and no LLM calls** — pure local filesystem analysis.

## Sections

| # | Section | Method |
|---|---------|--------|
| 1 | `sources` | file inventory by extension, excluded-dir pruning |
| 2 | `duplicates` | exact sha256 clusters + character-trigram Jaccard near pairs |
| 3 | `identity_collisions` | normalized titles (NFKC + casefold + separator strip) |
| 4 | `conflicting_candidates` | same case-folded stem, ≥2 distinct content hashes |
| 5 | `stale_references` | relative markdown links resolving to missing files |
| 6 | `unresolved_dates` | conservative: unparseable frontmatter date fields, impossible calendar tokens |
| 7 | `sensitive_exposure` | filename/content pattern presence only — **matched values are never captured** |
| 8 | `projection_readiness` | markdown ratio + frontmatter possession rate |
| 9 | `estimated_compile_work` | byte-based estimate with explicit, echoed coefficients |

## Usage

```bash
python -m akc_health_scan <root> --json out.json
# optional tuning
python -m akc_health_scan <root> --near-duplicate-threshold 0.9
```

```python
from akc_health_scan import HealthScanConfig, scan

report = scan("./my-corpus", HealthScanConfig(near_duplicate_threshold=0.9))
print(report.to_dict()["duplicates"])
```

Exit codes: `0` success, `2` bad path. All tunables/coefficients live in
`HealthScanConfig` and are echoed verbatim into every report.
