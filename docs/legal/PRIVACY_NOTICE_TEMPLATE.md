# Privacy Notice — Draft Data Map

> Privacy counsel must supply legal bases, entity/contact details, jurisdiction
> rights, transfer mechanisms, and final retention periods.

| Data                       | Purpose                          | Default storage              | Sharing                  | Retention owner |
| -------------------------- | -------------------------------- | ---------------------------- | ------------------------ | --------------- |
| account and membership     | authenticate, authorize, support | control-plane DB             | auth provider            | Privacy         |
| uploaded source            | requested processing             | private object storage       | none by default          | Product/Privacy |
| derived blocks/assets      | review and export                | private object storage/DB    | none by default          | Product/Privacy |
| optional Precision pages   | higher-quality processing        | scoped provider transmission | disclosed provider only  | Privacy         |
| job/quality/cost telemetry | operate, secure, bill            | logs/metrics without content | observability processors | SRE             |
| user corrections           | provide editor/reprocessing      | project data                 | none by default          | Product/Privacy |
| opt-in training candidate  | stated improvement purpose       | separate restricted pool     | approved training stack  | ML/Privacy      |
| payment reference          | billing/refund                   | billing DB/provider          | payment processor        | Finance         |
| audit/deletion receipt     | security/compliance evidence     | immutable audit store        | auditors when authorized | Security        |

## Required disclosures

- controller/processor roles and contact channels;
- categories, sources, purposes, legal bases, recipients, and transfers;
- region versus guaranteed data-residency behavior;
- account, project, source, derived, export, log, backup, and training retention;
- access, correction, deletion, portability, objection, restriction, complaint,
  and consent-withdrawal rights as applicable;
- cookies/analytics with sensitive payload minimization;
- automated processing and meaningful human review;
- security practices stated accurately and without absolute guarantees;
- subprocessor change process and breach notification channel;
- children/age policy.

## Product-to-notice checks

The product settings, upload estimate, external-provider consent, training
consent, deletion receipt, and published notice MUST use the same current
retention and sharing configuration. A configuration change cannot ship before
the notice and consent implications are reviewed.
