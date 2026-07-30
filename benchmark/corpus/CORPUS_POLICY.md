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

- Private beta: 1,500 pages, 150 documents, at least 50% Korean, at least ten
  document classes.
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
