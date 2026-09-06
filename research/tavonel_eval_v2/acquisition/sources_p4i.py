"""Declared acquisition inputs for P4i. Written and hashed before any fetch.

Candidate lists AND reserve ordering are frozen here, before any eligibility,
coverage or retrieval figure is computed. Reserves are appended in declared
order and consumed in that order: which reserve entry is reached depends only on
how many earlier candidates were admitted, never on how any of them scored.

The P4g lists are imported rather than retyped. A list that appears twice in a
repository is a list that will eventually disagree with itself, and the P4g
entries are already sealed by that protocol's acquisition receipt.
"""

from __future__ import annotations

from sources_p4g import (  # noqa: F401  (re-exported: the frozen P4g inputs)
    DART,
    ECFR_PARTS,
    ECFR_PARTS_RESERVE,
    GIT_PATH_RULE,
    GIT_REPOSITORIES,
    GIT_REPOSITORIES_RESERVE,
    LICENCES,
    NETWORK,
    REDISTRIBUTION,
    REVISION_SPACING,
    SEC_BASE_FORMS,
    SEC_ISSUERS,
    SEC_ISSUERS_RESERVE,
    SELECTION_RULE,
    USER_AGENT,
    WIKIPEDIA_ARTICLES,
    WIKIPEDIA_ARTICLES_RESERVE,
)

#: 550 attempted for headroom; 400 admitted across 4 families is the gate.
#: The two are different claims and INC-V2-016 is the record of what happens
#: when they are welded together.
ACQUISITION_TARGET = {
    "source_documents": 550,
    "status": "DESIRED TARGET, not a statistical endpoint",
    "breadth_gate": "at least 400 admitted across at least 4 families",
    "breadth_gate_provenance": (
        "inherited from P4g's G_P4G_SCALE, which required 400 before any result "
        "existed and which P4g failed at 321. Not a bar invented to fit 174."
    ),
    "power_gate": "eligible Q1 >= 190, on its own gate",
}

#: Acquisition quotas scaled up from P4g's PREDECLARED NOMINAL BALANCE RULE.
#: NOT the realized proportions that produced 174 — P4g's admitted mix was
#: 98 / 93 / 114 / 16, which is a different thing.
FAMILY_QUOTA = {
    "git_docs": 165,
    "regulation_ecfr": 165,
    "encyclopedia_wikipedia": 165,
    "sec_edgar": 55,
    "minimum_families": 4,
    "acquisition_target": 550,
    "breadth_floor": 400,
}

P4G_ADMITTED_MIX = {
    "git_docs": 98,
    "regulation_ecfr": 93,
    "encyclopedia_wikipedia": 114,
    "sec_edgar": 16,
    "note": "recorded here so the quotas above are never described as these",
}

#: Each family selects up to this multiple of its quota, then the admitted list
#: is truncated at the quota in declared order. P4g selected 376 and admitted
#: 300 because selection stopped at a quota of SELECTED documents while
#: attrition happened later.
OVER_SELECTION = {
    "factor": 1.5,
    "truncation": "at the quota, in declared order",
    "not_by_outcome": (
        "no coverage, eligibility or retrieval figure exists at acquisition "
        "time, so truncation cannot be conditioned on one"
    ),
}

#: Every rejected candidate carries one of these.
ADMISSION_FAILURE_CODES = (
    "PAYLOAD_UNAVAILABLE",
    "PARSE_FLOOR",
    "RELATION_FAILURE",
    "SOURCE_EXHAUSTION",
    "SPACING_NOT_MET",
    "NO_SOURCE_CHANGE",
    "LISTING_FAILED",
    "OTHER",
)

#: Raw reasons emitted by the fetchers, mapped onto the declared codes. Anything
#: unmapped becomes OTHER rather than silently vanishing.
FAILURE_CODE_MAP = {
    "FETCH_FAILED": "PAYLOAD_UNAVAILABLE",
    "INELIGIBLE_PARSE_FLOOR": "PARSE_FLOOR",
    "CANONICALISATION_FAILED": "PARSE_FLOOR",
    "INELIGIBLE_RELATION": "RELATION_FAILURE",
    "NO_PRIMARY_DOCUMENT": "RELATION_FAILURE",
    "INELIGIBLE_SINGLE_VERSION": "SOURCE_EXHAUSTION",
    "TOO_FEW_COMMITS": "SOURCE_EXHAUSTION",
    "TOO_FEW_REVISIONS": "SOURCE_EXHAUSTION",
    "NO_MARKDOWN_UNDER_PREFIX": "SOURCE_EXHAUSTION",
    "TREE_TRUNCATED": "SOURCE_EXHAUSTION",
    "NO_DEFAULT_BRANCH": "SOURCE_EXHAUSTION",
    "INELIGIBLE_SPACING_NOT_MET": "SPACING_NOT_MET",
    "INELIGIBLE_NO_SOURCE_CHANGE": "NO_SOURCE_CHANGE",
    "LISTING_FAILED": "LISTING_FAILED",
}

#: Additional CFR parts, third tranche, declared order.
ECFR_PARTS_RESERVE_2: tuple[tuple[str, str, str], ...] = (
    ("21", "211", "Current good manufacturing practice for finished pharmaceuticals"),
    ("40", "261", "Identification and listing of hazardous waste"),
    ("29", "1904", "Recording and reporting occupational injuries and illnesses"),
    ("49", "395", "Hours of service of drivers"),
    ("12", "1005", "Electronic fund transfers (Regulation E)"),
    ("17", "270", "Investment Company Act rules"),
    ("42", "483", "Requirements for states and long term care facilities"),
    ("7", "246", "Special supplemental nutrition program for women, infants and children"),
    ("47", "64", "Miscellaneous rules relating to common carriers"),
    ("45", "160", "General administrative requirements for health information"),
    ("14", "91", "General operating and flight rules"),
    ("50", "622", "Fisheries of the Caribbean, Gulf of Mexico and South Atlantic"),
)

#: Additional documentation trees, third tranche, declared order.
GIT_REPOSITORIES_RESERVE_2: tuple[dict[str, str], ...] = (
    {"owner": "kubernetes", "repo": "website", "prefix": "content/en/docs/setup/", "license": "CC-BY-4.0"},
    {"owner": "istio", "repo": "istio.io", "prefix": "content/en/docs/ops/", "license": "Apache-2.0"},
    {"owner": "grafana", "repo": "grafana", "prefix": "docs/sources/datasources/", "license": "AGPL-3.0"},
    {"owner": "prometheus", "repo": "alertmanager", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "opentelemetry", "repo": "opentelemetry.io", "prefix": "content/en/docs/collector/", "license": "Apache-2.0"},
    {"owner": "helm", "repo": "helm-www", "prefix": "content/en/blog/", "license": "Apache-2.0"},
    {"owner": "grpc", "repo": "grpc.io", "prefix": "content/en/blog/", "license": "Apache-2.0"},
    {"owner": "flutter", "repo": "website", "prefix": "src/content/ui/", "license": "CC-BY-4.0"},
    {"owner": "dotnet", "repo": "docs", "prefix": "docs/core/", "license": "CC-BY-4.0"},
    {"owner": "mdn", "repo": "content", "prefix": "files/en-us/web/css/", "license": "CC-BY-SA-2.5"},
    {"owner": "mdn", "repo": "content", "prefix": "files/en-us/web/javascript/guide/", "license": "CC-BY-SA-2.5"},
    {"owner": "rust-lang", "repo": "reference", "prefix": "src/", "license": "MIT OR Apache-2.0"},
)

#: Additional articles, third tranche, declared order.
WIKIPEDIA_ARTICLES_RESERVE_2: tuple[str, ...] = (
    "Radio telescope", "Osmosis", "Silt", "Chernobyl disaster", "Bicycle",
    "Coffee", "Tobacco", "Sugar", "Maize", "Potato", "Barley", "Olive oil",
    "Honey", "Vinegar", "Cheese", "Yeast", "Antenna (radio)", "Transistor",
    "Capacitor", "Magnetism", "Refraction", "Diffraction", "Entropy",
    "Thermodynamics", "Viscosity", "Surface tension", "Catalysis",
    "Electrolysis", "Corrosion", "Welding", "Casting", "Forging", "Ceramic",
    "Concrete", "Asphalt", "Insulation", "Ventilation", "Sewage treatment",
    "Landfill", "Recycling", "Biodiversity", "Ecosystem", "Savanna",
    "Taiga", "Steppe", "Fjord", "Delta (river)", "Karst", "Sand dune",
    "Avalanche", "Landslide", "Drought", "Flood", "Wildfire", "Lightning",
    "Cyclone", "Jet stream", "El Niño", "Gulf Stream", "Ocean current",
    "Photograph", "Microscope", "Telescope", "Spectroscopy", "Chromatography",
    "Mass spectrometry", "X-ray", "Ultrasound", "Anaesthesia", "Antiseptic",
    "Blood transfusion", "Organ transplantation", "Prosthesis", "Dentistry",
    "Epidemiology", "Quarantine", "Sanitation", "Nutrition", "Metabolism",
    "Hormone", "Neuron", "Synapse", "Retina", "Cochlea", "Skeleton",
    "Muscle", "Liver", "Kidney", "Lung", "Heart", "Pancreas", "Skin",
    "Archaeology", "Papyrus", "Parchment", "Alphabet", "Numeral system",
    "Calendar", "Clock", "Compass", "Map projection", "Surveying",
    "Navigation", "Sailing ship", "Railway", "Automobile", "Aircraft",
    "Rocket", "Satellite", "Submarine", "Canal lock", "Tunnel",
)

#: The declared order in which lists are consumed, per family. Reading this is
#: the whole answer to "why was that document acquired and not another".
CONSUMPTION_ORDER = {
    "git_docs": ["GIT_REPOSITORIES", "GIT_REPOSITORIES_RESERVE", "GIT_REPOSITORIES_RESERVE_2"],
    "regulation_ecfr": ["ECFR_PARTS", "ECFR_PARTS_RESERVE", "ECFR_PARTS_RESERVE_2"],
    "encyclopedia_wikipedia": [
        "WIKIPEDIA_ARTICLES",
        "WIKIPEDIA_ARTICLES_RESERVE",
        "WIKIPEDIA_ARTICLES_RESERVE_2",
    ],
    "sec_edgar": ["SEC_ISSUERS", "SEC_ISSUERS_RESERVE"],
    "frozen_before_any_fetch": True,
    "frozen_before_any_eligibility_result": True,
}

GIT_REPOSITORIES_ALL = GIT_REPOSITORIES + GIT_REPOSITORIES_RESERVE + GIT_REPOSITORIES_RESERVE_2
ECFR_PARTS_ALL = ECFR_PARTS + ECFR_PARTS_RESERVE + ECFR_PARTS_RESERVE_2
WIKIPEDIA_ARTICLES_ALL = (
    WIKIPEDIA_ARTICLES + WIKIPEDIA_ARTICLES_RESERVE + WIKIPEDIA_ARTICLES_RESERVE_2
)
SEC_ISSUERS_ALL = SEC_ISSUERS + SEC_ISSUERS_RESERVE
