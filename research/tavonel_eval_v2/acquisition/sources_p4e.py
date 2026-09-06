"""Declared acquisition inputs for P4e. Written and hashed before any fetch.

P4d failed `G_P4D_Q1_SCALE` at 67 against a bar of 100, and that failure is
preserved. It is **not** repaired by picking revision pairs until the count
clears — a cohort chosen against a target it can see is not a cohort. The cause
was structural and is fixed structurally: P4c and P4d used *adjacent* revisions,
and adjacent revisions of a long article or a CFR section move few units.

P4e declares a **revision-spacing rule per family**, frozen here before any
retrieval result exists. Spacing is stated as an ordinal or temporal separation
that can be evaluated from the revision list alone, with no reference to how
many units moved and none to any score.

The headroom is deliberate. A cohort designed to land near 100 would make the
gate the target; these settings aim well above it so the gate measures
sufficiency rather than aim.
"""

from __future__ import annotations

#: Frozen before any fetch. Every clause is decidable from revision metadata.
REVISION_SPACING = {
    "encyclopedia_wikipedia": {
        "rule": (
            "the newest revision, paired with the newest revision at least 180 "
            "days older than it. If the article has no such older revision in "
            "the fetched window, the article is excluded."
        ),
        "separation": "180 days",
        "decidable_from": "revision timestamps alone",
    },
    "regulation_ecfr": {
        "rule": (
            "the newest dated version of the section, paired with the oldest "
            "dated version the versioner reports for it. Sections with fewer "
            "than two dated versions are excluded."
        ),
        "separation": "maximal available ordinal separation",
        "decidable_from": "the versioner's date list alone",
    },
    "git_docs": {
        "rule": (
            "the pair already held whose after-revision has the most recent "
            "known_at, unchanged from P4c. Git documents are carried over so "
            "one family holds spacing constant while three vary it."
        ),
        "separation": "unchanged from P4c",
        "decidable_from": "the acquisition manifest alone",
    },
    "sec_edgar": {
        "rule": "the amendment pair already held, unchanged from P4c",
        "separation": "unchanged from P4c",
        "decidable_from": "the acquisition manifest alone",
    },
    "frozen_before_any_retrieval_result": True,
    "never_conditioned_on": [
        "how many units moved",
        "any retrieval score",
        "the Q1 count",
        "any gate outcome",
    ],
}

#: Source-document independence, carried from P4c unchanged.
SELECTION_RULE = {
    "one_pair_per_source_document": True,
    "container_cap": (
        "at most 6 documents per container — repository, issuer, CFR part. "
        "Raised from P4c's 4 because the document target is larger; the cap "
        "still stops one container dominating."
    ),
    "eligibility": (
        "both revisions parse, both yield at least 3 canonical units, the "
        "spacing rule for the family is satisfied, and the licence permits "
        "local research use"
    ),
    "frozen_before_any_retrieval_result": True,
}

#: Quotas fixed before results. Documents are taken in the declared order and
#: the list is truncated at the quota, never selected against an outcome.
FAMILY_QUOTA = {
    "encyclopedia_wikipedia": 24,
    "regulation_ecfr": 30,
    "git_docs": 7,
    "sec_edgar": 4,
    "minimum_families": 4,
    "minimum_documents": 40,
}

#: Query-construction inputs. Enforced structurally by ``retrieval/intent_view``
#: rather than checked after the fact — the founder's ruling is that answer
#: independence is a provenance property, not a string property.
QUERY_FIELDS = {
    "permitted": [
        "document_title",
        "document_identity",
        "document_type",
        "anchor_heading",
        "parent_heading",
    ],
    "forbidden": [
        "atom_body",
        "answer_span",
        "oracle_answer",
        "current_revision_id",
        "superseded_revision_id",
        "revision_window",
        "before_after_label",
        "current_superseded_state",
        "retrieval_result",
    ],
    "enforcement": (
        "the query builder's only argument is an IntentView carrying exactly "
        "the permitted fields. A forbidden source is not filtered out of the "
        "finished query; it is never reachable by the process that writes it."
    ),
    "machine_identifiers": {
        "decision": "excluded from every query, unchanged from P4c",
        "affected": ["SEC CIK", "bare numeric CFR section token"],
    },
}

#: 17 CFR securities, 40 CFR environmental, 21 CFR food and drug, 29 CFR safety,
#: 12 CFR banking, 45 CFR health privacy. Widened from P4c's five parts to reach
#: the document quota without lifting the per-container cap.
ECFR_PARTS: tuple[tuple[str, str, str], ...] = (
    ("17", "240", "Securities Exchange Act general rules and regulations"),
    ("17", "275", "Investment Advisers Act rules"),
    ("40", "63", "National emission standards for hazardous air pollutants"),
    ("21", "314", "Applications for FDA approval to market a new drug"),
    ("29", "1910", "Occupational safety and health standards"),
    ("12", "1026", "Truth in Lending (Regulation Z)"),
    ("45", "164", "Security and privacy of health information"),
)

#: Long-lived articles with steady revision activity across subject areas, so
#: the routing task is not one topic seen from many angles. Widened from P4c's
#: twenty to absorb exclusions from the 180-day spacing rule.
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
    "Glacier",
    "Vaccine",
    "Nuclear fusion",
    "Roman Republic",
    "Photovoltaics",
    "Groundwater",
    "Neural network",
    "Antarctica",
    "Desalination",
    "Printing press",
)

DART = {
    "family": "dart_kr",
    "endpoint": "https://opendart.fss.or.kr/api/list.json",
    "credential_env": "DART_API_KEY / crtfc_key",
    "state": "BLOCKED_MISSING_CREDENTIAL",
    "note": (
        "carried forward from P4c, where every call returned status 010, an "
        "unregistered certification key. A missing credential is a founder "
        "decision. Per the ruling of 2026-08-22 it blocks nothing: the "
        "four-family evidence stands and research continues without it."
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
