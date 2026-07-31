export const SEC_PUBLIC_FIXTURE = {
  source: {
    authority: "U.S. Securities and Exchange Commission",
    entity: "Apple Inc.",
    cik: "0000320193",
    ticker: "AAPL",
    form: "10-K",
    accession: "0000320193-25-000079",
    filingDate: "2025-10-31",
    acceptedAt: "2025-10-31T06:01:26-04:00",
    reportPeriod: "2025-09-27",
    document: "aapl-20250927.htm",
    documentSizeBytes: 1_520_208,
    archiveUrl:
      "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
    filingIndexUrl:
      "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm",
    sourceLocation:
      "Form 10-K page 22 · Products and Services Performance · dollars in millions",
    verificationDate: "2026-07-31",
    archiveSha256: null,
    archiveSha256Status:
      "Pending controlled archive-byte retrieval; no checksum is invented.",
  },
  facts: [
    {
      id: "fact-total-net-sales-2025",
      label: "Total net sales",
      period: "2025",
      valueMillions: 416_161,
      unit: "USD millions",
      sourceRow: "Total net sales",
      sourceColumn: "2025",
      evidenceStatus: "source-verified",
    },
    {
      id: "fact-products-2025",
      label: "Products",
      period: "2025",
      valueMillions: 307_003,
      unit: "USD millions",
      sourceRow: "Products",
      sourceColumn: "2025",
      evidenceStatus: "source-verified",
    },
    {
      id: "fact-services-2025",
      label: "Services",
      period: "2025",
      valueMillions: 109_158,
      unit: "USD millions",
      sourceRow: "Services",
      sourceColumn: "2025",
      evidenceStatus: "source-verified",
    },
    {
      id: "fact-total-net-sales-2024",
      label: "Total net sales",
      period: "2024",
      valueMillions: 391_035,
      unit: "USD millions",
      sourceRow: "Total net sales",
      sourceColumn: "2024",
      evidenceStatus: "source-verified",
    },
    {
      id: "fact-total-net-sales-2023",
      label: "Total net sales",
      period: "2023",
      valueMillions: 383_285,
      unit: "USD millions",
      sourceRow: "Total net sales",
      sourceColumn: "2023",
      evidenceStatus: "source-verified",
    },
  ],
  productCategories: [
    { label: "iPhone", values: [209_586, 201_183, 200_583] },
    { label: "Mac", values: [33_708, 29_984, 29_357] },
    { label: "iPad", values: [28_023, 26_694, 28_300] },
    {
      label: "Wearables, Home and Accessories",
      values: [35_686, 37_005, 39_845],
    },
    { label: "Services", values: [109_158, 96_169, 85_200] },
    { label: "Total net sales", values: [416_161, 391_035, 383_285] },
  ],
  markdown: `---
title: Apple Inc. 2025 Form 10-K — Revenue Evidence
entity: Apple Inc.
cik: "0000320193"
form: 10-K
accession: "0000320193-25-000079"
period_end: 2025-09-27
source_authority: U.S. Securities and Exchange Commission
source_location: Form 10-K page 22
unit: USD millions
---

# Products and Services Performance

| Category | 2025 | 2024 | 2023 |
|---|---:|---:|---:|
| iPhone | 209,586 | 201,183 | 200,583 |
| Mac | 33,708 | 29,984 | 29,357 |
| iPad | 28,023 | 26,694 | 28,300 |
| Wearables, Home and Accessories | 35,686 | 37,005 | 39,845 |
| Services | 109,158 | 96,169 | 85,200 |
| **Total net sales** | **416,161** | **391,035** | **383,285** |

> Evidence: SEC accession 0000320193-25-000079, Form 10-K page 22.`,
  notes: [
    {
      id: "note-apple",
      title: "Apple Inc.",
      type: "Entity",
      properties: ["CIK 0000320193", "Ticker AAPL", "SEC registrant"],
      evidence: ["filing identity", "accession metadata"],
    },
    {
      id: "note-filing",
      title: "Apple 2025 Form 10-K",
      type: "Filing",
      properties: [
        "Period ended 2025-09-27",
        "Filed 2025-10-31",
        "Accession 0000320193-25-000079",
      ],
      evidence: ["SEC filing index", "Inline XBRL document"],
    },
    {
      id: "note-revenue",
      title: "FY2025 total net sales",
      type: "Metric",
      properties: ["USD 416,161 million", "FY2025", "source row preserved"],
      evidence: ["Form 10-K page 22", "Total net sales · 2025 cell"],
    },
    {
      id: "note-services",
      title: "FY2025 services net sales",
      type: "Metric",
      properties: ["USD 109,158 million", "FY2025", "category fact"],
      evidence: ["Form 10-K page 22", "Services · 2025 cell"],
    },
  ],
  relations: [
    {
      subject: "Apple 2025 Form 10-K",
      predicate: "filed_by",
      object: "Apple Inc.",
    },
    {
      subject: "Apple 2025 Form 10-K",
      predicate: "reports",
      object: "FY2025 total net sales",
    },
    {
      subject: "FY2025 total net sales",
      predicate: "includes",
      object: "FY2025 services net sales",
    },
    {
      subject: "FY2025 total net sales",
      predicate: "period_end",
      object: "2025-09-27",
    },
  ],
} as const;

export type SecPublicFixture = typeof SEC_PUBLIC_FIXTURE;
