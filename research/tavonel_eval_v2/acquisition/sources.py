"""Declared acquisition inputs for the P0 development smoke.

Written before the smoke runs and hashed into the acquisition manifest, so the
issuer and repository lists are inputs of record rather than something chosen
after seeing which pairs happened to look convenient.
"""

from __future__ import annotations

#: SEC EDGAR issuers scanned for amendment pairs. Large, long-lived filers, so
#: the scan is not conditioned on whether a particular amendment exists.
SEC_ISSUERS: tuple[tuple[str, str], ...] = (
    ("AAPL", "0000320193"),
    ("MSFT", "0000789019"),
    ("TSLA", "0001318605"),
    ("NVDA", "0001045810"),
    ("INTC", "0000050863"),
    ("AMZN", "0001018724"),
    ("GOOGL", "0001652044"),
    ("META", "0001326801"),
    ("JPM", "0000019617"),
    ("XOM", "0000034088"),
    ("KO", "0000021344"),
    ("BA", "0000012927"),
    ("GE", "0000040545"),
    ("F", "0000037996"),
    ("PFE", "0000078003"),
)

#: Base forms whose amendment relation is verifiable from the issuer's own
#: submissions index. Every one of these carries a reportDate, so the amendment
#: pairs to exactly one original by (base form, reportDate). Forms filed without
#: a reportDate -- SC 13G, 144, SCHEDULE 13G -- are excluded: pairing them would
#: mean guessing, which the protocol forbids.
SEC_BASE_FORMS: frozenset[str] = frozenset(
    {"8-K", "10-K", "10-Q", "20-F", "DEF 14A", "S-1", "S-4", "40-F"}
)

#: Documentation files in permissively licensed repositories. Prose, not code:
#: each of these records user-facing or operational knowledge that is revised
#: over time, which is the property the corpus needs.
GIT_DOCS: tuple[dict[str, str], ...] = (
    {
        "owner": "prometheus",
        "repo": "prometheus",
        "path": "docs/configuration/configuration.md",
        "license": "Apache-2.0",
    },
    {
        "owner": "prometheus",
        "repo": "prometheus",
        "path": "docs/querying/functions.md",
        "license": "Apache-2.0",
    },
    {
        "owner": "prometheus",
        "repo": "prometheus",
        "path": "docs/querying/basics.md",
        "license": "Apache-2.0",
    },
    {
        "owner": "grafana",
        "repo": "loki",
        "path": "docs/sources/configure/_index.md",
        "license": "AGPL-3.0",
    },
    {
        "owner": "kubernetes",
        "repo": "website",
        "path": "content/en/docs/concepts/workloads/controllers/deployment.md",
        "license": "CC-BY-4.0",
    },
    {
        "owner": "kubernetes",
        "repo": "website",
        "path": "content/en/docs/concepts/services-networking/service.md",
        "license": "CC-BY-4.0",
    },
    {
        "owner": "rust-lang",
        "repo": "book",
        "path": "src/ch04-01-what-is-ownership.md",
        "license": "MIT OR Apache-2.0",
    },
    {
        "owner": "astral-sh",
        "repo": "uv",
        "path": "docs/concepts/projects/dependencies.md",
        "license": "MIT OR Apache-2.0",
    },
)

#: Bytes acquired under these licences stay on local disk. The IP gate forbids
#: release; these fields exist so a later release decision has the facts rather
#: than a guess.
REDISTRIBUTION: str = "LOCAL_ONLY_NO_REDISTRIBUTION_WHILE_IP_GATE_CLOSED"
