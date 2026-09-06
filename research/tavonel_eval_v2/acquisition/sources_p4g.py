"""Declared acquisition inputs for P4g. Written and hashed before any fetch.

P4g targets 400 source documents across at least four families, with 120 in the
markdown family and a container cap of 8. Those targets are frozen in
``protocols/P4g_cohort_expansion.yaml``; this file declares the concrete inputs
that reach them, and is sealed by the acquisition receipt.

Two things in here are extensions rather than inheritances, and saying so is the
point of writing them down:

``P4g`` states ``spacing_rule: unchanged from P4e``. For eCFR and Wikipedia that
is literally satisfiable — P4e declared date rules and they are copied verbatim.
For ``git_docs`` and ``sec_edgar`` it is not: P4e's rule for both was *the pair
already held*, and the manifest holds 8 git documents and 10 SEC documents. A
rule that selects from a held set of 8 cannot produce 120. The under-specification
is recorded as ``INC-V2-012``; the extension below is declared here, before any
fetch and before any eligibility, coverage or retrieval figure exists, which is
the property the anti-fitting rules actually protect. P4g itself is not modified.
"""

from __future__ import annotations

#: Frozen before any fetch. Every clause is decidable from revision metadata
#: alone — no clause mentions how much a document changed or any later score.
REVISION_SPACING = {
    "encyclopedia_wikipedia": {
        "rule": (
            "the newest revision, paired with the newest revision at least 180 "
            "days older than it. Articles without such a revision in the "
            "fetched window are excluded."
        ),
        "separation": "180 days",
        "decidable_from": "revision timestamps alone",
        "provenance": "verbatim from P4e",
    },
    "regulation_ecfr": {
        "rule": (
            "the newest dated version of the section, paired with the oldest "
            "dated version the versioner reports for it. Sections with fewer "
            "than two dated versions are excluded."
        ),
        "separation": "maximal available ordinal separation",
        "decidable_from": "the versioner's date list alone",
        "provenance": "verbatim from P4e",
    },
    "git_docs": {
        "rule": (
            "for each admitted path, the newest commit touching it, paired with "
            "the newest commit touching it at least 180 days older. Paths "
            "without such a commit in the fetched window are excluded."
        ),
        "separation": "180 days",
        "decidable_from": "commit timestamps alone",
        "provenance": (
            "EXTENSION, not inheritance. P4e's git rule was 'the pair already "
            "held', which selects from 8 documents and cannot yield 120. The "
            "separation matches the Wikipedia rule rather than being chosen: it "
            "is the only temporal separation P4e declared for a family whose "
            "revisions are timestamped commits. See INC-V2-012."
        ),
    },
    "sec_edgar": {
        "rule": (
            "an amendment pair: same CIK, same base form, same period of "
            "report, exactly one original and the earliest amendment, as "
            "published in the issuer submissions index."
        ),
        "separation": "the amendment relation itself, not a duration",
        "decidable_from": "the submissions index alone",
        "provenance": (
            "EXTENSION in scale only. The relation is P4c's, unchanged. What "
            "changes is that pairs are drawn from the live index for 20 issuers "
            "rather than from the 10 already on disk. See INC-V2-012."
        ),
    },
    "frozen_before_any_fetch": True,
    "frozen_before_any_retrieval_result": True,
    "never_conditioned_on": [
        "how many units moved",
        "any retrieval score",
        "any coverage or eligibility status",
        "the Q1 count",
        "any gate outcome",
    ],
}

#: Source-document independence. The cap is P4g's, raised from P4e's 6.
SELECTION_RULE = {
    "one_pair_per_source_document": True,
    "container_cap": 8,
    "container_is": {
        "git_docs": "the repository",
        "sec_edgar": "the issuer",
        "regulation_ecfr": "the CFR part",
        "encyclopedia_wikipedia": (
            "the article. Wikipedia has no sub-site container, and the cap "
            "exists to stop one editorial process dominating the cohort — each "
            "article has its own. The family quota is what bounds Wikipedia's "
            "share, and it is declared below."
        ),
    },
    "eligibility": (
        "both revisions parse, both yield at least 3 canonical units, the two "
        "payloads differ, the spacing rule for the family is satisfied, and the "
        "licence permits local research use"
    ),
    "ordering": (
        "documents are taken in the declared order and the list is truncated at "
        "the quota. Nothing is selected against an outcome, because no outcome "
        "exists when the selection runs."
    ),
    "frozen_before_any_fetch": True,
}

#: 400 documents. No family exceeds 30%, so no single family's behaviour can be
#: mistaken for the cohort's.
FAMILY_QUOTA = {
    "git_docs": 120,
    "regulation_ecfr": 120,
    "encyclopedia_wikipedia": 100,
    "sec_edgar": 60,
    "minimum_families": 4,
    "target_documents": 400,
    "markdown_family_documents": 120,
}

#: 18 parts x cap 8 = up to 144 candidates for a quota of 120. Widened from
#: P4e's 7 to reach the quota without lifting the per-container cap.
ECFR_PARTS: tuple[tuple[str, str, str], ...] = (
    ("17", "240", "Securities Exchange Act general rules and regulations"),
    ("17", "275", "Investment Advisers Act rules"),
    ("40", "63", "National emission standards for hazardous air pollutants"),
    ("21", "314", "Applications for FDA approval to market a new drug"),
    ("29", "1910", "Occupational safety and health standards"),
    ("12", "1026", "Truth in Lending (Regulation Z)"),
    ("45", "164", "Security and privacy of health information"),
    ("14", "121", "Operating requirements: domestic, flag and supplemental operations"),
    ("49", "571", "Federal motor vehicle safety standards"),
    ("7", "205", "National Organic Program"),
    ("47", "73", "Radio broadcast services"),
    ("30", "250", "Oil and gas and sulphur operations in the outer continental shelf"),
    ("10", "50", "Domestic licensing of production and utilization facilities"),
    ("42", "422", "Medicare Advantage program"),
    ("24", "3280", "Manufactured home construction and safety standards"),
    ("26", "1", "Income tax"),
    ("33", "165", "Regulated navigation areas and limited access areas"),
    ("50", "17", "Endangered and threatened wildlife and plants"),
)

#: Documentation trees in permissively licensed repositories. Prose, not code.
#: The path prefix is part of the declaration: it fixes *which* markdown a
#: repository contributes before anything is fetched, so the admitted set is not
#: a choice made later.
GIT_REPOSITORIES: tuple[dict[str, str], ...] = (
    {"owner": "prometheus", "repo": "prometheus", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "grafana", "repo": "loki", "prefix": "docs/sources/", "license": "AGPL-3.0"},
    {
        "owner": "kubernetes",
        "repo": "website",
        "prefix": "content/en/docs/concepts/",
        "license": "CC-BY-4.0",
    },
    {"owner": "rust-lang", "repo": "book", "prefix": "src/", "license": "MIT OR Apache-2.0"},
    {"owner": "nodejs", "repo": "node", "prefix": "doc/api/", "license": "MIT"},
    {"owner": "reactjs", "repo": "react.dev", "prefix": "src/content/learn/", "license": "CC-BY-4.0"},
    {"owner": "vercel", "repo": "next.js", "prefix": "docs/", "license": "MIT"},
    {
        "owner": "microsoft",
        "repo": "TypeScript-Website",
        "prefix": "packages/documentation/copy/en/handbook-v2/",
        "license": "MIT",
    },
    {"owner": "istio", "repo": "istio.io", "prefix": "content/en/docs/concepts/", "license": "Apache-2.0"},
    {"owner": "rust-lang", "repo": "rust", "prefix": "src/doc/", "license": "MIT OR Apache-2.0"},
    {"owner": "tensorflow", "repo": "docs", "prefix": "site/en/guide/", "license": "Apache-2.0"},
    {"owner": "flutter", "repo": "website", "prefix": "src/content/", "license": "CC-BY-4.0"},
    {"owner": "dotnet", "repo": "docs", "prefix": "docs/csharp/", "license": "CC-BY-4.0"},
    {"owner": "angular", "repo": "angular", "prefix": "adev/src/content/guide/", "license": "MIT"},
    {"owner": "vuejs", "repo": "docs", "prefix": "src/guide/", "license": "MIT"},
    {"owner": "mdn", "repo": "content", "prefix": "files/en-us/web/http/", "license": "CC-BY-SA-2.5"},
    {"owner": "traefik", "repo": "traefik", "prefix": "docs/content/", "license": "MIT"},
    {"owner": "helm", "repo": "helm-www", "prefix": "content/en/docs/", "license": "Apache-2.0"},
    {"owner": "grpc", "repo": "grpc.io", "prefix": "content/en/docs/", "license": "Apache-2.0"},
    {"owner": "etcd-io", "repo": "website", "prefix": "content/en/docs/", "license": "Apache-2.0"},
    {"owner": "hashicorp", "repo": "terraform", "prefix": "website/docs/", "license": "BUSL-1.1"},
    {"owner": "gitlabhq", "repo": "gitlab-foss", "prefix": "doc/", "license": "MIT"},
    {"owner": "docker", "repo": "docs", "prefix": "content/manuals/", "license": "Apache-2.0"},
    {"owner": "openssl", "repo": "openssl", "prefix": "doc/man7/", "license": "Apache-2.0"},
)

#: Markdown path admission inside a repository, decided before any fetch.
GIT_PATH_RULE = {
    "extension": ".md",
    "under": "the repository's declared prefix",
    "order": "lexicographic by full path",
    "take": "the first 8 that satisfy the spacing rule",
    "excluded_names": ["_index.md", "index.md", "README.md", "SUMMARY.md", "TOC.md"],
    "why_excluded": (
        "landing and table-of-contents pages are navigation, not the revised "
        "prose the corpus is about. The exclusion is by filename, decidable "
        "without reading the file."
    ),
}

#: 20 issuers x cap 8 = up to 160 candidates for a quota of 60.
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
    ("WMT", "0000104169"),
    ("CVX", "0000093410"),
    ("MRK", "0000310158"),
    ("T", "0000732717"),
    ("DIS", "0001744489"),
)

SEC_BASE_FORMS: frozenset[str] = frozenset(
    {"8-K", "10-K", "10-Q", "20-F", "DEF 14A", "S-1", "S-4", "40-F"}
)

#: 100 articles across subject areas, so the routing task is not one topic seen
#: from many angles. Ordered as declared; truncated at the quota, never selected.
WIKIPEDIA_ARTICLES: tuple[str, ...] = (
    "Ozone layer", "Photosynthesis", "Byzantine Empire", "Quantum entanglement",
    "Monetary policy", "Antibiotic resistance", "Plate tectonics", "Machine translation",
    "Coral reef", "Silk Road", "Immune system", "Renewable energy", "Volcano",
    "Prime number", "Bauhaus", "Mitochondrion", "Great Barrier Reef", "Cryptography",
    "Amazon rainforest", "Industrial Revolution", "Glacier", "Vaccine", "Nuclear fusion",
    "Roman Republic", "Photovoltaics", "Groundwater", "Neural network", "Antarctica",
    "Desalination", "Printing press", "Black hole", "Antibiotic", "Permafrost",
    "Ottoman Empire", "Genome", "Semiconductor", "Tsunami", "Cholera", "Aral Sea",
    "Enzyme", "Radiocarbon dating", "Hanseatic League", "Superconductivity", "Malaria",
    "Wind power", "Cartography", "Bee", "Inflation", "Aqueduct", "Vitamin C",
    "Tectonic uplift", "Mangrove", "Steam engine", "Penicillin", "Meiji Restoration",
    "Sahara", "Photolithography", "Tuberculosis", "Lithium-ion battery", "Monsoon",
    "Gothic architecture", "Protein folding", "Nitrogen cycle", "Feudalism",
    "Bacteriophage", "Hydroelectricity", "Mount Everest", "Papermaking", "Insulin",
    "Trans-Saharan trade", "Seismology", "Chlorophyll", "Great Depression",
    "Nuclear reactor", "Carbon capture and storage", "Ribosome", "Silk", "Estuary",
    "Antikythera mechanism", "Yellow fever", "Geothermal energy", "Watermill",
    "Stem cell", "Salt", "Dendrochronology", "Coral bleaching", "Bronze Age",
    "Optical fiber", "Pollination", "Hurricane", "Smallpox", "Canal", "Alloy",
    "Peat", "Byzantine art", "Radar", "Tide", "Vaccination", "Sundial", "Wetland",
)

DART = {
    "family": "dart_kr",
    "endpoint": "https://opendart.fss.or.kr/api/list.json",
    "credential_env": "DART_API_KEY / crtfc_key",
    "state": "BLOCKED_MISSING_CREDENTIAL",
    "note": (
        "carried forward unchanged. A missing credential is a founder decision "
        "and it blocks nothing: the four-family evidence stands without it."
    ),
}

REDISTRIBUTION = "LOCAL_ONLY_NO_REDISTRIBUTION_WHILE_IP_GATE_CLOSED"

LICENCES = {
    "sec_edgar": "US federal government work, public domain (17 USC 105)",
    "git_docs": "per-repository, recorded with each document",
    "regulation_ecfr": "US federal government work, public domain (17 USC 105)",
    "encyclopedia_wikipedia": "CC BY-SA 4.0",
}

#: Read-only GETs against public endpoints. The GitHub listing calls are
#: authenticated purely for the rate limit; nothing is written, no private
#: resource is read, and no credential reaches any other host.
NETWORK = {
    "method": "GET only",
    "github_auth": "bearer token from the environment, for rate limit only",
    "credential_leaves_repository": False,
    "writes": "none",
}

USER_AGENT = "tavonel-research/0.1 (claude23@vieworks.com)"


# ---------------------------------------------------------------------------
# Top-up. Declared before the top-up fetch, after the first pass fell short.
# ---------------------------------------------------------------------------

#: INC-V2-014. The first pass admitted 300 documents against a target of 400.
#: The shortfall is mechanical and family-specific, and the exclusion ledger
#: says exactly where it came from: 2,320 CFR sections carry a single dated
#: version, 25 markdown paths have fewer than two commits and 22 miss the 180-day
#: separation, and SEC amendment pairs whose primary document yields three
#: canonical units are simply scarce — 13 admitted from 20 issuers.
#:
#: Nothing here is conditioned on an eligibility, coverage or retrieval figure,
#: because none exists: the cohort has not been scored. What it is conditioned on
#: is a **document count**, which P4g's `never_conditioned_on` list does not
#: contain and could not sensibly contain — a target of 400 that may not be
#: revised toward from below is not a target.
TOP_UP = {
    "incident": "INC-V2-014",
    "reason": "the declared lists yielded 300 of a target 400",
    "conditioned_on": "the admitted document count only",
    "not_conditioned_on": [
        "any eligibility count",
        "any coverage status",
        "any retrieval score",
        "the Q1 count",
    ],
    "frozen_before_the_top_up_fetch": True,
    "spacing_rules": "unchanged; the reserves are additional inputs, not new rules",
    "selection_rule": "unchanged; container cap 8, one pair per source document",
    "sec_is_expected_to_stay_short": (
        "amendment pairs with a parseable primary document are scarce and no "
        "list of issuers changes that. The family is reported at whatever it "
        "reaches; it is not padded and it is not dropped."
    ),
}

#: Quotas for the top-up pass. Balanced so no family exceeds 30% of the target,
#: which is the same constraint the first pass was built under.
TOP_UP_QUOTA = {
    "git_docs": 120,
    "regulation_ecfr": 120,
    "encyclopedia_wikipedia": 120,
    "sec_edgar": 60,
    "minimum_families": 4,
    "target_documents": 400,
}

#: Additional documentation trees, same admission rule.
GIT_REPOSITORIES_RESERVE: tuple[dict[str, str], ...] = (
    {"owner": "cockroachdb", "repo": "docs", "prefix": "src/current/v24.1/", "license": "CC-BY-4.0"},
    {"owner": "apache", "repo": "kafka", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "opensearch-project", "repo": "documentation-website", "prefix": "_search-plugins/", "license": "Apache-2.0"},
    {"owner": "kubernetes", "repo": "website", "prefix": "content/en/docs/tasks/", "license": "CC-BY-4.0"},
    {"owner": "prometheus", "repo": "docs", "prefix": "content/docs/", "license": "Apache-2.0"},
    {"owner": "grafana", "repo": "grafana", "prefix": "docs/sources/alerting/", "license": "AGPL-3.0"},
    {"owner": "envoyproxy", "repo": "envoy", "prefix": "examples/", "license": "Apache-2.0"},
    {"owner": "opentelemetry", "repo": "opentelemetry.io", "prefix": "content/en/docs/concepts/", "license": "Apache-2.0"},
    {"owner": "kubernetes", "repo": "website", "prefix": "content/en/docs/reference/access-authn-authz/", "license": "CC-BY-4.0"},
    {"owner": "istio", "repo": "istio.io", "prefix": "content/en/docs/tasks/", "license": "Apache-2.0"},
)

#: Additional CFR parts, chosen for breadth of subject matter as before.
ECFR_PARTS_RESERVE: tuple[tuple[str, str, str], ...] = (
    ("21", "820", "Quality system regulation for medical devices"),
    ("40", "141", "National primary drinking water regulations"),
    ("29", "1926", "Safety and health regulations for construction"),
    ("49", "192", "Transportation of natural gas by pipeline"),
    ("12", "1024", "Real Estate Settlement Procedures (Regulation X)"),
    ("17", "230", "General rules and regulations, Securities Act of 1933"),
    ("42", "482", "Conditions of participation for hospitals"),
    ("7", "319", "Foreign quarantine notices"),
    ("47", "76", "Multichannel video and cable television service"),
    ("40", "60", "Standards of performance for new stationary sources"),
    ("21", "101", "Food labeling"),
    ("14", "25", "Airworthiness standards: transport category airplanes"),
)

#: Additional articles, same 180-day rule.
WIKIPEDIA_ARTICLES_RESERVE: tuple[str, ...] = (
    "Ocean acidification", "Antimatter", "Kelp forest", "Byzantine music",
    "Hydrogen fuel", "Tundra", "Lidar", "Rice", "Cement", "Nuclear waste",
    "Anaerobic digestion", "Fault (geology)", "Copper", "Whale", "Sourdough",
    "Erosion", "Telegraphy", "Volcanology", "Diabetes", "Aquifer",
    "Photodetector", "Bridge", "Rubber", "Locust", "Sea level rise",
    "Hydrothermal vent", "Cuneiform", "Glass", "Wheat", "Solar cell",
    "Lighthouse", "Compost", "Cotton", "Dam", "Timber", "Windmill",
    "Fermentation", "Textile", "Iron", "Salt marsh",
)

#: Additional issuers. Expected to add little, and recorded either way.
SEC_ISSUERS_RESERVE: tuple[tuple[str, str], ...] = (
    ("CSCO", "0000858877"), ("ORCL", "0001341439"), ("IBM", "0000051143"),
    ("QCOM", "0000804328"), ("TXN", "0000097476"), ("HON", "0000773840"),
    ("CAT", "0000018230"), ("MMM", "0000066740"), ("UNH", "0000731766"),
    ("ABT", "0000001800"), ("LLY", "0000059478"), ("BMY", "0000014272"),
    ("GS", "0000886982"), ("MS", "0000895421"), ("C", "0000831001"),
)
