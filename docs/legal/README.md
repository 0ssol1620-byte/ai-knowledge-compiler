# Legal Launch Templates

These are issue-spotting templates, not legal advice and not publishable text.
Qualified counsel and the privacy/security owners must approve localized final
documents before paid beta.

## Required documents

- Terms of Service covering account use, uploaded-content rights, prohibited
  content, service limits, credits/refunds, suspension, termination, and
  accuracy/professional-advice disclaimers.
- Privacy Notice covering controller/processor roles, data categories,
  purposes, legal bases, retention, deletion, transfers, subprocessors,
  security, data-subject rights, analytics, and training defaults.
- Data Processing Addendum covering instructions, confidentiality, controls,
  subprocessors, transfer mechanism, incidents, deletion/return, and audits.
- Subprocessor Register with provider, purpose, data categories, region,
  retention, transfer mechanism, DPA date, and change-notice procedure.
- Acceptable Use and infringement-reporting process.

## Non-negotiable product statements

- Customer content is not used for training by default.
- External model/API transmission is opt-in and disclosed before processing.
- Opt-in training states purpose, retention, de-identification, withdrawal, and
  limits on deleting influence from already deployed models.
- Enterprise is training opt-out by default.
- Uploaders warrant sufficient rights to process content.
- AI output is not guaranteed accurate and is not professional advice.
- Credit reservation, consumption, release, failure refund, reversal, and
  storage retention are described in plain language.

## Approval matrix

| Item             | Product | Security | Privacy | Finance | Counsel |
| ---------------- | ------: | -------: | ------: | ------: | ------: |
| Terms            |       R |        C |       C |       C |       A |
| Privacy Notice   |       C |        C |       R |       I |       A |
| DPA              |       I |        C |       R |       I |       A |
| Subprocessors    |       I |        C |       R |       I |       A |
| Credits/refunds  |       R |        I |       C |       A |       C |
| Training consent |       R |        C |       A |       I |       C |

`A` is accountable, `R` responsible, `C` consulted, and `I` informed.

## Release evidence

Store approved document version, locale, approval date, approvers, immutable
hash, publication URL, effective date, and the product/configuration version to
which it applies. Material changes require user notice and renewed consent
where applicable.
