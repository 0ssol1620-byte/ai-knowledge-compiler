"""Fresh candidate lists for the VBC1 **feasibility probe**. Burned by design.

This is not the confirmatory cohort and must never become it. The probe exists
to answer one question that a projection cannot: on sources chosen for
value-bearing structure, what fraction of admitted documents survives the whole
frozen chain — value fact, coverage completeness, single contrast?

Every lineage listed here is spent the moment the probe reports. Its eligibility
outcome will have been seen, which is exactly the condition that excluded P4i's
lineages and MODEL_ENDPOINT_V1's ten survivors from the confirmatory cohort. The
same rule applies to its own author's lists.

Nothing here overlaps P4i. The repositories, CFR parts, articles and issuers
below were checked against `sources_p4i.*_ALL` and are disjoint from all four.

Selection principle, declared before the fetch: each entry is chosen because its
*shape* is likely to bind a labelled quantity — an options table with a Default
column, a regulation part carrying fee or limit schedules, an article whose
infobox holds counts or dates. It is never chosen for a known outcome; none of
these lineages has been fetched, scored or inspected.
"""

from __future__ import annotations

from typing import Any

PROBE = {
    "purpose": "measure the admission rate of the frozen chain on fresh value-shaped sources",
    "burned_after_use": True,
    "why_burned": (
        "the probe reports eligibility. A lineage whose eligibility has been seen "
        "cannot enter a confirmatory cohort without making selection an outcome."
    ),
    "not_the_confirmatory_cohort": True,
    "disjoint_from": ["P4i", "MODEL_ENDPOINT_V1 survivors"],
}

#: Deliberately small. The probe is a measurement, not an acquisition.
PROBE_QUOTA = {
    "git_docs": 14,
    "regulation_ecfr": 14,
    "encyclopedia_wikipedia": 14,
    "sec_edgar": 6,
}

OVER_SELECTION = {"factor": 1.5, "truncation": "declared order"}

#: Documentation repositories whose pages carry option/default/limit tables.
GIT_REPOSITORIES: tuple[dict[str, str], ...] = (
    {"owner": "redis", "repo": "redis-doc", "prefix": "docs/", "license": "CC-BY-SA-4.0"},
    {"owner": "nginx", "repo": "nginx.org", "prefix": "xml/", "license": "BSD-2-Clause"},
    {"owner": "ansible", "repo": "ansible-documentation", "prefix": "docs/", "license": "GPL-3.0"},
    {"owner": "elastic", "repo": "logstash", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "spark", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "airflow", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "containerd", "repo": "containerd", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "cilium", "repo": "cilium", "prefix": "Documentation/", "license": "Apache-2.0"},
    {"owner": "openshift", "repo": "openshift-docs", "prefix": "modules/", "license": "Apache-2.0"},
    {"owner": "minio", "repo": "docs", "prefix": "source/", "license": "Apache-2.0"},
    {"owner": "influxdata", "repo": "docs-v2", "prefix": "content/", "license": "MIT"},
    {"owner": "timescale", "repo": "docs", "prefix": "api/", "license": "Apache-2.0"},
    {"owner": "vitessio", "repo": "website", "prefix": "content/", "license": "Apache-2.0"},
    {"owner": "ceph", "repo": "ceph", "prefix": "doc/", "license": "LGPL-2.1"},
    {"owner": "openstack", "repo": "nova", "prefix": "doc/", "license": "Apache-2.0"},
    {"owner": "moby", "repo": "moby", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "hashicorp", "repo": "vault", "prefix": "website/content/", "license": "BUSL-1.1"},
    {"owner": "hashicorp", "repo": "consul", "prefix": "website/content/", "license": "BUSL-1.1"},
    {"owner": "kubernetes", "repo": "kubeadm", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "argoproj", "repo": "argo-cd", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "fluent", "repo": "fluent-bit-docs", "prefix": "pipeline/", "license": "Apache-2.0"},
)

#: CFR parts that carry labelled quantities — fees, limits, thresholds, periods.
ECFR_PARTS: tuple[tuple[str, str, str], ...] = (
    ("13", "121", "Small Business Administration size standards"),
    ("20", "404", "Social Security old-age and disability insurance"),
    ("20", "416", "Supplemental Security Income"),
    ("26", "301", "Procedure and administration"),
    ("29", "778", "Overtime compensation"),
    ("29", "1915", "Occupational safety for shipyard employment"),
    ("31", "1010", "Financial recordkeeping and reporting"),
    ("34", "668", "Student assistance general provisions"),
    ("38", "3", "Veterans adjudication"),
    ("40", "98", "Mandatory greenhouse gas reporting"),
    ("40", "112", "Oil pollution prevention"),
    ("41", "301", "Federal travel regulation, temporary duty allowances"),
    ("42", "412", "Prospective payment systems for inpatient services"),
    ("42", "413", "Payment for end-stage renal disease services"),
    ("45", "155", "Health insurance exchanges"),
    ("46", "108", "Marine engineering equipment"),
    ("48", "52", "Federal acquisition solicitation provisions"),
    ("49", "173", "Hazardous materials shippers"),
    ("49", "393", "Parts and accessories for safe operation"),
    ("7", "273", "Supplemental nutrition assistance certification"),
    ("9", "381", "Poultry products inspection"),
)

#: Articles whose infoboxes bind counts, dates, areas and elevations.
WIKIPEDIA_ARTICLES: tuple[str, ...] = (
    "Reykjavík",
    "Tallinn",
    "Ljubljana",
    "Bratislava",
    "Podgorica",
    "Vilnius",
    "Riga",
    "Valletta",
    "Luxembourg City",
    "Andorra la Vella",
    "San Marino",
    "Monaco-Ville",
    "Nuuk",
    "Tórshavn",
    "Mariehamn",
    "Longyearbyen",
    "Ushuaia",
    "Hobart",
    "Dunedin",
    "Whitehorse",
    "Yellowknife",
    "Iqaluit",
    "Kiruna",
    "Rovaniemi",
    "Murmansk",
    "Anchorage",
    "Reggio Calabria",
    "Trondheim",
    "Galway",
    "Aberdeen",
    "Bergen",
    "Turku",
)

#: Issuers whose filings carry structured cover-page facts.
SEC_ISSUERS: tuple[tuple[str, str], ...] = (
    ("DE", "0000315189"),
    ("UPS", "0001090727"),
    ("FDX", "0001048911"),
    ("LMT", "0000936468"),
    ("RTX", "0000101829"),
    ("NOC", "0001133421"),
    ("EMR", "0000032604"),
    ("ETN", "0001551182"),
    ("ADM", "0000007084"),
    ("PG", "0000080424"),
    ("COST", "0000909832"),
    ("TGT", "0000027419"),
)

CONSUMPTION_ORDER: dict[str, Any] = {
    "frozen_before_any_fetch": True,
    "frozen_before_any_eligibility_result": True,
    "rule": "declared list order; no reordering after any figure exists",
    "git_docs": [r["owner"] + "/" + r["repo"] for r in GIT_REPOSITORIES],
    "regulation_ecfr": [title + " " + part for title, part, _ in ECFR_PARTS],
    "encyclopedia_wikipedia": list(WIKIPEDIA_ARTICLES),
    "sec_edgar": [ticker for ticker, _ in SEC_ISSUERS],
}
