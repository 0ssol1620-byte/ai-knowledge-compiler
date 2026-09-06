"""Declared roots for the VBC2 confirmatory acquisition. Frozen before any history.

These are *roots*, not lineages. The lineage list is expanded from them by
`freeze_vbc2_lineages.py` and sealed before a single revision is read, because
the expansion needs the network and the freeze must precede any value.

Everything here is disjoint from the three predecessors by construction and by
check: P4i's declared lists, the ten `MODEL_ENDPOINT_V1` survivors (whose
lineages are P4i's), and the 45 lineages of the V1 feasibility probe.

The family shares are V1's, carried forward unchanged. The V1 probe's per-family
outcome is not a reason to re-weight, and re-weighting after seeing a yield is
the thing two protocols already forbid in writing.
"""

from __future__ import annotations

from typing import Any

FAMILY_SHARE = {
    "git_docs": 0.40,
    "regulation_ecfr": 0.30,
    "encyclopedia_wikipedia": 0.20,
    "sec_edgar": 0.10,
}

#: The primary cohort target. The floor is 190 distinct lineages; this is the
#: acquisition target that leaves headroom above it, not a statistical endpoint.
PRIMARY_TARGET = 260

FAMILY_QUOTA = {
    "git_docs": 104,
    "regulation_ecfr": 78,
    "encyclopedia_wikipedia": 52,
    "sec_edgar": 26,
}

#: Frozen on API availability, compute and reproducibility. Never moved to reach
#: a number, and never tuned against an observed yield.
HISTORY = {
    "horizon_days": 1460,
    "acquisition_cutoff": "2026-08-23T00:00:00Z",
    "max_revisions_inspected_per_lineage": 12,
    "walk_order": "newest first, stopping at the first qualifying transition",
    "basis": "API availability, compute and reproducibility",
    "explicitly_not_basis": "observed value-fact yield",
}

#: Repositories whose documentation binds labelled quantities in tables, and
#: whose files change often enough for a history walk to find a transition.
#: None appears in P4i or in the V1 probe.
GIT_ROOTS: tuple[dict[str, str], ...] = (
    {"owner": "postgres", "repo": "postgres", "prefix": "doc/src/sgml/", "license": "PostgreSQL"},
    {"owner": "mysql", "repo": "mysql-server", "prefix": "Docs/", "license": "GPL-2.0"},
    {"owner": "sqlite", "repo": "sqlite", "prefix": "doc/", "license": "Public-Domain"},
    {"owner": "python", "repo": "cpython", "prefix": "Doc/library/", "license": "PSF-2.0"},
    {"owner": "golang", "repo": "go", "prefix": "doc/", "license": "BSD-3-Clause"},
    {"owner": "denoland", "repo": "docs", "prefix": "runtime/", "license": "MIT"},
    {"owner": "pnpm", "repo": "pnpm.io", "prefix": "docs/", "license": "MIT"},
    {"owner": "pypa", "repo": "pip", "prefix": "docs/", "license": "MIT"},
    {"owner": "astral-sh", "repo": "uv", "prefix": "docs/", "license": "MIT"},
    {"owner": "astral-sh", "repo": "ruff", "prefix": "docs/", "license": "MIT"},
    {"owner": "pola-rs", "repo": "polars", "prefix": "docs/", "license": "MIT"},
    {"owner": "duckdb", "repo": "duckdb-web", "prefix": "docs/", "license": "MIT"},
    {"owner": "clickhouse", "repo": "clickhouse-docs", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "flink", "prefix": "docs/content/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "cassandra", "prefix": "doc/", "license": "Apache-2.0"},
    {"owner": "elastic", "repo": "elasticsearch", "prefix": "docs/", "license": "Elastic-2.0"},
    {"owner": "opensearch-project", "repo": "OpenSearch", "prefix": "doc/", "license": "Apache-2.0"},
    {"owner": "rabbitmq", "repo": "rabbitmq-website", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "nats-io", "repo": "nats.docs", "prefix": "nats-server/", "license": "Apache-2.0"},
    {"owner": "temporalio", "repo": "documentation", "prefix": "docs/", "license": "MIT"},
    {"owner": "dapr", "repo": "docs", "prefix": "daprdocs/", "license": "Apache-2.0"},
    {"owner": "knative", "repo": "docs", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "linkerd", "repo": "website", "prefix": "linkerd.io/content/", "license": "Apache-2.0"},
    {"owner": "kedacore", "repo": "keda-docs", "prefix": "content/", "license": "Apache-2.0"},
    {"owner": "crossplane", "repo": "docs", "prefix": "content/", "license": "Apache-2.0"},
    {"owner": "backstage", "repo": "backstage", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "grafana", "repo": "tempo", "prefix": "docs/sources/", "license": "AGPL-3.0"},
    {"owner": "grafana", "repo": "mimir", "prefix": "docs/sources/", "license": "AGPL-3.0"},
    {"owner": "thanos-io", "repo": "thanos", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "open-telemetry", "repo": "opentelemetry-collector", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "jaegertracing", "repo": "documentation", "prefix": "content/", "license": "Apache-2.0"},
    {"owner": "vectordotdev", "repo": "vector", "prefix": "website/content/", "license": "MPL-2.0"},
    {"owner": "kubernetes-sigs", "repo": "kind", "prefix": "site/content/", "license": "Apache-2.0"},
    {"owner": "k3s-io", "repo": "docs", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "rancher", "repo": "rancher-docs", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "traefik", "repo": "traefik-helm-chart", "prefix": "traefik/", "license": "Apache-2.0"},
)

#: CFR parts carrying labelled quantities. Disjoint from P4i and the V1 probe.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("2", "200", "Uniform administrative requirements and cost principles"),
    ("5", "550", "Pay administration"),
    ("7", "210", "National school lunch program"),
    ("7", "226", "Child and adult care food program"),
    ("10", "20", "Standards for protection against radiation"),
    ("10", "430", "Energy conservation program for appliances"),
    ("12", "217", "Capital adequacy of bank holding companies"),
    ("12", "1002", "Equal credit opportunity"),
    ("14", "39", "Airworthiness directives"),
    ("14", "135", "Commuter and on-demand operations"),
    ("16", "1500", "Hazardous substances"),
    ("17", "39", "Registered entities"),
    ("19", "351", "Antidumping and countervailing duties"),
    ("21", "133", "Cheeses and related cheese products"),
    ("21", "184", "Direct food substances affirmed as GRAS"),
    ("21", "610", "General biological products standards"),
    ("23", "635", "Construction and maintenance"),
    ("24", "982", "Housing choice voucher program"),
    ("27", "5", "Labeling and advertising of distilled spirits"),
    ("29", "1926", "Safety and health regulations for construction"),
    ("30", "75", "Mandatory safety standards, underground coal mines"),
    ("32", "199", "Civilian health and medical program"),
    ("33", "154", "Facilities transferring oil or hazardous material"),
    ("36", "800", "Protection of historic properties"),
    ("40", "180", "Tolerances for pesticide chemicals in food"),
    ("40", "268", "Land disposal restrictions"),
    ("40", "1065", "Engine testing procedures"),
    ("42", "409", "Hospital insurance benefits"),
    ("42", "435", "Medicaid eligibility"),
    ("45", "147", "Health insurance reform requirements"),
    ("46", "170", "Stability requirements for all inspected vessels"),
    ("47", "15", "Radio frequency devices"),
    ("48", "31", "Contract cost principles and procedures"),
    ("49", "213", "Track safety standards"),
    ("49", "563", "Event data recorders"),
    ("50", "648", "Fisheries of the northeastern United States"),
)

#: Categories expanded into article lineages before any history is read. A
#: category is a declared root; the members it yields are frozen with a receipt.
WIKIPEDIA_CATEGORY_ROOTS: tuple[str, ...] = (
    "Category:Cities in Bavaria",
    "Category:Communes of Corse-du-Sud",
    "Category:Municipalities of Iceland",
    "Category:Cities and towns in Hokkaido",
    "Category:Districts of Vienna",
    "Category:Municipalities of Ticino",
    "Category:Cities in Tasmania",
    "Category:Municipalities of Luxembourg",
    "Category:Cities in Estonia",
    "Category:Populated places in Malta",
)

#: Issuers absent from P4i and the V1 probe.
SEC_ROOTS: tuple[tuple[str, str], ...] = (
    ("SO", "0000092122"),
    ("DUK", "0001326160"),
    ("NEE", "0000753308"),
    ("AEP", "0000004904"),
    ("EXC", "0001109357"),
    ("XEL", "0000072903"),
    ("WEC", "0000783325"),
    ("ED", "0001047862"),
    ("PEG", "0000788784"),
    ("SRE", "0001032208"),
    ("PPL", "0000922224"),
    ("CMS", "0000811156"),
    ("DTE", "0000936340"),
    ("AEE", "0001002910"),
    ("CNP", "0001130310"),
    ("NI", "0001111711"),
)

CONSUMPTION_ORDER: dict[str, Any] = {
    "frozen_before_any_history_read": True,
    "frozen_before_any_value_read": True,
    "rule": "declared root order, then lineage order within a root as expanded",
    "git_docs": [r["owner"] + "/" + r["repo"] for r in GIT_ROOTS],
    "regulation_ecfr": [title + "-" + part for title, part, _ in ECFR_ROOTS],
    "encyclopedia_wikipedia": list(WIKIPEDIA_CATEGORY_ROOTS),
    "sec_edgar": [ticker for ticker, _ in SEC_ROOTS],
}

ADMISSION_FAILURE_CODES = (
    "LISTING_FAILED",
    "PAYLOAD_UNAVAILABLE",
    "PARSE_FLOOR",
    "TOO_FEW_REVISIONS",
    "NO_QUALIFYING_TRANSITION",
    "AMBIGUOUS_VALUE_FACT",
    "LINEAGE_NOT_FRESH",
    "BEYOND_FAMILY_QUOTA",
    "SOURCE_EXHAUSTION",
    "OTHER",
)
