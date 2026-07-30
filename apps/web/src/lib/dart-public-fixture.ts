export const DART_PUBLIC_FIXTURE = {
  source: "OpenDART",
  company: "JTC",
  stockCode: "950170",
  corporationCode: "01041828",
  report: "Quarterly report (2026.05)",
  receiptNumber: "20260730000413",
  receiptDate: "2026-07-30",
  sourceUrl: "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260730000413",
  archiveSha256:
    "3b7876350a2032969e65be1a46c9b9527d19ec2f4d3452b9e696bc8d8cabf655",
  sourceSha256:
    "312d03bcd23951c21948021dc2ea115e2f5be58b7c5a1eb23d9dc9da1f98e6a3",
  statement: "Consolidated statement of comprehensive income",
  unit: "JPY",
  currentPeriod: "2026 Q1",
  priorPeriod: "2025 Q1",
  rows: [
    {
      label: "Revenue",
      current: "4,902,490,901",
      prior: "10,048,464,180",
      taxonomy: "ifrs-full_Revenue",
      sourceLine: 3669,
    },
    {
      label: "Cost of sales",
      current: "915,603,778",
      prior: "2,364,444,189",
      taxonomy: "ifrs-full_CostOfSales",
      sourceLine: 3681,
    },
    {
      label: "Gross profit",
      current: "3,986,887,123",
      prior: "7,684,019,991",
      taxonomy: "ifrs-full_GrossProfit",
      sourceLine: 3693,
    },
    {
      label: "Operating income",
      current: "227,642,463",
      prior: "1,168,794,326",
      taxonomy: "dart_OperatingIncomeLoss",
      sourceLine: 3717,
    },
  ],
} as const;
