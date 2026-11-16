# Corpus Policy

## Separation

- `synthetic`: harmless generated fixtures committed to this repository; CI
  contract tests only.
- `private-evaluation`: licensed or internally owned documents and immutable
  annotations; restricted object store.
- `holdout`: evaluation-only split hidden from prompt/model/router tuning.
- `training-candidates`: opt-in corrections awaiting rights, privacy,
  de-identification, and quality review.
- `private-security`: controlled dangerous samples; never in this repository.

No customer content enters a corpus by default. An opt-in correction is never
placed directly into evaluation or training. It needs consent lineage, purpose,
retention, rights verification, tenant/identity removal, secret/PII scanning,
annotation review, and deletion propagation.

## Minimum corpus gates

- Private beta (EG-04, ADR-009): 1,500 pages, 150 documents, at least ten
  document classes, and per-stratum floors (pages / minimum documents):
  en_native 225/20, en_tables 225/20, ko_native 250/20, ko_scan 150/15,
  ko_tables 150/15, ko_hwp 75/10, slides 100/10, formulas 75/10,
  handwriting 75/10, distorted 100/10, adversarial 75/10. A document counts
  toward its stratum's floor with at most ceil(floor / 10) pages; a shortfall is
  never covered by another stratum; a fixed-language stratum holds only that
  language; a synthetic document never sits in ko_scan, handwriting or
  distorted and counts toward no floor except adversarial's. `manifest.py`
  checks these. At least five distinct issuers/publishers (authors, for
  handwriting) per stratum, adversarial pages being constructed hostile cases
  and never degradations, and no rasterised print in a scan stratum are
  corpus policy, checked at freeze by the corpus builder's freeze receipt from
  the source records; a stratum the receipt cannot verify leaves EG-04 not
  passed.
- Public beta: 5,000 pages, 500 documents, real low-quality/complex/Office
  documents, plus an undisclosed holdout.
- Competitive training phase: 20,000+ pages across personal, work, study,
  research, forms, and long documents.

## Ground truth

Annotate transcript, block type, bbox1000/polygon, reading order, heading tree,
list hierarchy, table grid/spans, formula LaTeX, figure-caption links,
header/footer, exact numbers/dates/units, source-to-Markdown mapping, and
knowledge-note evidence.

## Safety

Synthetic adversarial fixtures exercise parsers without containing reusable
exploits. Actual malware, archive bombs, exploit files, private documents, and
credentials are prohibited. Repository scanning must reject them.
