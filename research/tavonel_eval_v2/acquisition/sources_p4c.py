"""Declared acquisition inputs for P4c. Written and hashed before any fetch.

Four families, and the reason there are four rather than the five originally
directed is recorded here rather than in a footnote: **DART is blocked on a
missing credential.** `opendart.fss.or.kr` answers, but every call returns
`status 010`, an unregistered certification key. A missing secret is not an
agent's call, so DART is declared, attempted at fetch time, and recorded as
`BLOCKED_MISSING_CREDENTIAL` with the API's own response — never quietly
dropped and never substituted for silently.

The selection rule below is frozen because P4b's `G_P4B_B_LINEAGE` failed partly
on cohort construction: 26 revision pairs drawn from 12 documents meant three
pairs of the same file competed as separate routing targets while being
identical in every field a question may name. P4c admits **one revision pair per
source document**, chosen by a rule that cannot see a retrieval result.
"""

from __future__ import annotations

#: One pair per source document. Every clause is decidable before any question
#: is scored, and none of them mentions a score.
SELECTION_RULE = {
    "one_pair_per_source_document": True,
    "git_docs": (
        "among the consecutive-commit pairs held for that document, the pair "
        "whose after-revision has the most recent known_at; ties broken by the "
        "lexicographically smallest pair identifier"
    ),
    "sec_edgar": (
        "a source document is (CIK, base form, period of report), which already "
        "admits at most one amendment pair"
    ),
    "regulation_ecfr": "the two most recent distinct dated versions of the section",
    "encyclopedia_wikipedia": "the two most recent revisions of the article at fetch time",
    "container_cap": (
        "at most 4 documents per container — repository, issuer, CFR part — so "
        "no single container dominates the routing task"
    ),
    "eligibility": (
        "both revisions parse, both yield at least 3 canonical units, and the "
        "licence permits local research use"
    ),
    "frozen_before_any_retrieval_result": True,
}

#: Query-construction inputs. The forbidden list is the operative half.
QUERY_FIELDS = {
    "permitted": [
        "source-provided document title",
        "issuer, project or document identity a user would normally have",
        "document or form type",
        "leaf heading",
        "immediate parent heading",
    ],
    "forbidden": [
        "answer span",
        "a token taken from the body in order to identify the answer",
        "the oracle-current revision identifier",
        "the revision window",
        "any before/after label",
        "any current/superseded indicator",
    ],
    "machine_identifiers": {
        "decision": "excluded from every query",
        "affected": ["SEC CIK", "eCFR section number as a bare numeric token"],
        "reason": (
            "a CIK is machine routing metadata. A person asking about a filing "
            "says the company's name, not its ten-digit central index key. P4b "
            "put ticker and CIK in the query together and its SEC routing looked "
            "strong for a reason that has nothing to do with how anyone asks a "
            "question. Machine identifiers may be indexed — they are "
            "source-provided — but they are never injected into user intent."
        ),
    },
}

#: 17 CFR is securities regulation, 40 CFR environmental, 21 CFR food and drug.
#: Parts chosen for size and amendment activity, before any of them was fetched.
ECFR_PARTS: tuple[tuple[str, str, str], ...] = (
    ("17", "240", "Securities Exchange Act general rules and regulations"),
    ("17", "275", "Investment Advisers Act rules"),
    ("40", "63", "National emission standards for hazardous air pollutants"),
    ("21", "314", "Applications for FDA approval to market a new drug"),
    ("29", "1910", "Occupational safety and health standards"),
)

#: Long-lived encyclopedia articles with steady revision activity, spread across
#: subject areas so the routing task is not one topic seen from five angles.
WIKIPEDIA_ARTICLES: tuple[str, ...] = (
    "Ozone layer",
    "Photosynthesis",
    "Byzantine Empire",
    "Quantum entanglement",
    "Monetary policy",
    "Antibiotic resistance",
    "Plate tectonics",
    "Machine translation",
    "Coral reef",
    "Silk Road",
    "Immune system",
    "Renewable energy",
    "Volcano",
    "Prime number",
    "Bauhaus",
    "Mitochondrion",
    "Great Barrier Reef",
    "Cryptography",
    "Amazon rainforest",
    "Industrial Revolution",
)

DART = {
    "family": "dart_kr",
    "endpoint": "https://opendart.fss.or.kr/api/list.json",
    "credential_env": "DART_API_KEY / crtfc_key",
    "state": "ATTEMPTED_AT_FETCH_TIME",
    "note": (
        "declared so its absence is recorded rather than inferred from the "
        "family list. A missing credential is a founder decision."
    ),
}

REDISTRIBUTION = "LOCAL_ONLY_NO_REDISTRIBUTION_WHILE_IP_GATE_CLOSED"

LICENCES = {
    "sec_edgar": "US federal government work, public domain (17 USC 105)",
    "git_docs": "per-repository, recorded with each document",
    "regulation_ecfr": "US federal government work, public domain (17 USC 105)",
    "encyclopedia_wikipedia": "CC BY-SA 4.0",
}

USER_AGENT = "tavonel-research/0.1 (claude23@vieworks.com)"
