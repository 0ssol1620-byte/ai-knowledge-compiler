"""Which reader rescues which, per element -- measured, never assumed.

The Arena leaderboard answers "who is best". On OmniDocBench's 1,651 pages that
is ovisocr2 on text and reading order, with paddleocr_vl_1_6 level with it on
formula, table and TEDS. It is the wrong question for a router, because the
answer flips with the benchmark: the same ovisocr2 that leads OmniDocBench text
sits ninth on olmOCR-Bench, and mineru_vlm leads there while sitting fifth here.

This module holds the answer to the question a router actually asks: *given the
reader I ran, which second reader recovers the pages it got wrong?* That is a
different measurement, and the 2026-09-06 complementarity study made it from the
per-page edit distances the campaign had already produced -- no new inference,
no GPU spend.

Two properties of the data matter more than any single number.

1.  **The best partner depends on the element.** For a paddleocr_vl_1_6 baseline
    the strongest rescuer is ovisocr2 on text, table and reading order, but
    infinity_parser2_flash on formula. A router that picks one partner for
    everything throws away the difference.

2.  **Each measured pair has a floor.** Paddle and Ovis are wrong together on
    11.4% of text pages, 22.9% of table pages, 35.7% of reading-order pages and
    44.7% of formula pages. The selected Paddle and Flash formula pair is wrong
    together on 42.8%. These campaign-specific pair limits do not bound every
    possible two-model arrangement. A second read is a recovery step, not a guarantee.

Every rate here carries its denominator, because a rescue rate is measured over
the pages the baseline got wrong, never over the corpus.

Provenance
----------
Both artifacts live in
``research/model_arena_20260903/reports/complementarity_20260906/``.

``complementarity_rescue_matrix.json``
    sha256 ``5528b7ec9afde1fd450bd82563360cf884d5c6d85998232171bc97dfdac3d174``
``complementarity_oracle_matrix.json``
    sha256 ``2efa03bc44824542c310a8fc10d0935b51317780240be4e4dc9717a0745bfaaf``

"Wrong" is ``edit > 0.05`` -- the study's discrete threshold, chosen because
``tau = 0`` calls a floating-point zero a failure. **It is not calibrated
against a TAVONEL corpus**, and no number here is a promise about a customer's
documents. The rows are a frozen record of one campaign on one public benchmark.

Generated from the artifact rather than typed. ``test_complementarity.py``
re-reads both files and fails if a digit here has drifted from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Route
from .preflight import PageMetrics

_REPORT_DIR = "research/model_arena_20260903/reports/complementarity_20260906"

COMPLEMENTARITY_ARTIFACT = f"{_REPORT_DIR}/complementarity_rescue_matrix.json"
COMPLEMENTARITY_SHA256 = "5528b7ec9afde1fd450bd82563360cf884d5c6d85998232171bc97dfdac3d174"
ORACLE_ARTIFACT = f"{_REPORT_DIR}/complementarity_oracle_matrix.json"
ORACLE_SHA256 = "2efa03bc44824542c310a8fc10d0935b51317780240be4e4dc9717a0745bfaaf"

#: A page counts as wrong for an element when its edit distance exceeds this.
WRONG_EDIT_THRESHOLD = 0.05


class ParseElement(StrEnum):
    """The four surfaces the study scored separately."""

    TEXT = "text"
    FORMULA = "formula"
    TABLE = "table"
    READING_ORDER = "reading_order"


@dataclass(frozen=True, slots=True)
class RescueMeasurement:
    """One directed measurement: how often ``peer`` is right where ``baseline`` is wrong."""

    element: ParseElement
    baseline: str
    peer: str
    rescue_rate: float
    baseline_wrong_pages: int
    scored_pages: int
    both_wrong_rate: float

    @property
    def denominator(self) -> str:
        """The sentence a rate may never be published without."""
        return (
            f"{self.baseline_wrong_pages} pages the baseline got wrong, "
            f"of {self.scored_pages} scored for {self.element.value}"
        )


#: (element, baseline, peer, rescue_rate, baseline_wrong_pages, scored_pages,
#: both_wrong_rate), ordered by element, then baseline, then strongest rescuer
#: first -- so the first match in `rescues_for` is the one to use.
_MEASURED_ROWS: tuple[tuple[str, str, str, float, int, int, float], ...] = (
    ("text", "deepseek", "ovis", 0.539642, 391, 1557, 0.115607),
    ("text", "deepseek", "paddle", 0.434783, 391, 1557, 0.141940),
    ("text", "deepseek", "flash", 0.396419, 391, 1557, 0.151574),
    ("text", "deepseek", "glm", 0.383632, 391, 1557, 0.154785),
    ("text", "deepseek", "opus", 0.373402, 391, 1557, 0.157354),
    ("text", "flash", "ovis", 0.477612, 335, 1557, 0.112396),
    ("text", "flash", "paddle", 0.379104, 335, 1557, 0.133590),
    ("text", "flash", "deepseek", 0.295522, 335, 1557, 0.151574),
    ("text", "flash", "opus", 0.280597, 335, 1557, 0.154785),
    ("text", "flash", "glm", 0.205970, 335, 1557, 0.170841),
    ("text", "glm", "ovis", 0.596200, 421, 1557, 0.109184),
    ("text", "glm", "deepseek", 0.427553, 421, 1557, 0.154785),
    ("text", "glm", "paddle", 0.420428, 421, 1557, 0.156712),
    ("text", "glm", "opus", 0.401425, 421, 1557, 0.161850),
    ("text", "glm", "flash", 0.368171, 421, 1557, 0.170841),
    ("text", "opus", "ovis", 0.587379, 412, 1557, 0.109184),
    ("text", "opus", "paddle", 0.507282, 412, 1557, 0.130379),
    ("text", "opus", "flash", 0.415049, 412, 1557, 0.154785),
    ("text", "opus", "deepseek", 0.405340, 412, 1557, 0.157354),
    ("text", "opus", "glm", 0.388350, 412, 1557, 0.161850),
    ("text", "ovis", "glm", 0.162562, 203, 1557, 0.109184),
    ("text", "ovis", "opus", 0.162562, 203, 1557, 0.109184),
    ("text", "ovis", "flash", 0.137931, 203, 1557, 0.112396),
    ("text", "ovis", "paddle", 0.128079, 203, 1557, 0.113680),
    ("text", "ovis", "deepseek", 0.113300, 203, 1557, 0.115607),
    ("text", "paddle", "ovis", 0.439873, 316, 1557, 0.113680),
    ("text", "paddle", "opus", 0.357595, 316, 1557, 0.130379),
    ("text", "paddle", "flash", 0.341772, 316, 1557, 0.133590),
    ("text", "paddle", "deepseek", 0.300633, 316, 1557, 0.141940),
    ("text", "paddle", "glm", 0.227848, 316, 1557, 0.156712),
    ("formula", "deepseek", "paddle", 0.246073, 191, 313, 0.460064),
    ("formula", "deepseek", "ovis", 0.204188, 191, 313, 0.485623),
    ("formula", "deepseek", "flash", 0.188482, 191, 313, 0.495208),
    ("formula", "deepseek", "opus", 0.162304, 191, 313, 0.511182),
    ("formula", "deepseek", "glm", 0.062827, 191, 313, 0.571885),
    ("formula", "flash", "paddle", 0.309278, 194, 313, 0.428115),
    ("formula", "flash", "ovis", 0.242268, 194, 313, 0.469649),
    ("formula", "flash", "deepseek", 0.201031, 194, 313, 0.495208),
    ("formula", "flash", "opus", 0.159794, 194, 313, 0.520767),
    ("formula", "flash", "glm", 0.061856, 194, 313, 0.581470),
    ("formula", "glm", "paddle", 0.425287, 261, 313, 0.479233),
    ("formula", "glm", "ovis", 0.402299, 261, 313, 0.498403),
    ("formula", "glm", "opus", 0.333333, 261, 313, 0.555911),
    ("formula", "glm", "deepseek", 0.314176, 261, 313, 0.571885),
    ("formula", "glm", "flash", 0.302682, 261, 313, 0.581470),
    ("formula", "opus", "paddle", 0.286458, 192, 313, 0.437700),
    ("formula", "opus", "ovis", 0.244792, 192, 313, 0.463259),
    ("formula", "opus", "deepseek", 0.166667, 192, 313, 0.511182),
    ("formula", "opus", "flash", 0.151042, 192, 313, 0.520767),
    ("formula", "opus", "glm", 0.093750, 192, 313, 0.555911),
    ("formula", "ovis", "paddle", 0.146341, 164, 313, 0.447284),
    ("formula", "ovis", "opus", 0.115854, 164, 313, 0.463259),
    ("formula", "ovis", "flash", 0.103659, 164, 313, 0.469649),
    ("formula", "ovis", "deepseek", 0.073171, 164, 313, 0.485623),
    ("formula", "ovis", "glm", 0.048780, 164, 313, 0.498403),
    ("formula", "paddle", "flash", 0.151899, 158, 313, 0.428115),
    ("formula", "paddle", "opus", 0.132911, 158, 313, 0.437700),
    ("formula", "paddle", "ovis", 0.113924, 158, 313, 0.447284),
    ("formula", "paddle", "deepseek", 0.088608, 158, 313, 0.460064),
    ("formula", "paddle", "glm", 0.050633, 158, 313, 0.479233),
    ("table", "deepseek", "ovis", 0.375661, 189, 458, 0.257642),
    ("table", "deepseek", "paddle", 0.354497, 189, 458, 0.266376),
    ("table", "deepseek", "flash", 0.126984, 189, 458, 0.360262),
    ("table", "deepseek", "glm", 0.116402, 189, 458, 0.364629),
    ("table", "deepseek", "opus", 0.005291, 189, 458, 0.410480),
    ("table", "flash", "paddle", 0.427230, 213, 458, 0.266376),
    ("table", "flash", "ovis", 0.422535, 213, 458, 0.268559),
    ("table", "flash", "deepseek", 0.225352, 213, 458, 0.360262),
    ("table", "flash", "glm", 0.187793, 213, 458, 0.377729),
    ("table", "flash", "opus", 0.004695, 213, 458, 0.462882),
    ("table", "glm", "ovis", 0.626959, 319, 458, 0.259825),
    ("table", "glm", "paddle", 0.605016, 319, 458, 0.275109),
    ("table", "glm", "deepseek", 0.476489, 319, 458, 0.364629),
    ("table", "glm", "flash", 0.457680, 319, 458, 0.377729),
    ("table", "glm", "opus", 0.018809, 319, 458, 0.683406),
    ("table", "opus", "ovis", 0.706278, 446, 458, 0.286026),
    ("table", "opus", "paddle", 0.697309, 446, 458, 0.294760),
    ("table", "opus", "deepseek", 0.578475, 446, 458, 0.410480),
    ("table", "opus", "flash", 0.524664, 446, 458, 0.462882),
    ("table", "opus", "glm", 0.298206, 446, 458, 0.683406),
    ("table", "ovis", "paddle", 0.198473, 131, 458, 0.229258),
    ("table", "ovis", "deepseek", 0.099237, 131, 458, 0.257642),
    ("table", "ovis", "glm", 0.091603, 131, 458, 0.259825),
    ("table", "ovis", "flash", 0.061069, 131, 458, 0.268559),
    ("table", "ovis", "opus", 0.000000, 131, 458, 0.286026),
    ("table", "paddle", "ovis", 0.222222, 135, 458, 0.229258),
    ("table", "paddle", "deepseek", 0.096296, 135, 458, 0.266376),
    ("table", "paddle", "flash", 0.096296, 135, 458, 0.266376),
    ("table", "paddle", "glm", 0.066667, 135, 458, 0.275109),
    ("table", "paddle", "opus", 0.000000, 135, 458, 0.294760),
    ("reading_order", "deepseek", "ovis", 0.216180, 754, 1638, 0.360806),
    ("reading_order", "deepseek", "opus", 0.169761, 754, 1638, 0.382173),
    ("reading_order", "deepseek", "paddle", 0.159151, 754, 1638, 0.387057),
    ("reading_order", "deepseek", "flash", 0.133952, 754, 1638, 0.398657),
    ("reading_order", "deepseek", "glm", 0.092838, 754, 1638, 0.417582),
    ("reading_order", "flash", "ovis", 0.190014, 721, 1638, 0.356532),
    ("reading_order", "flash", "paddle", 0.148405, 721, 1638, 0.374847),
    ("reading_order", "flash", "opus", 0.124827, 721, 1638, 0.385226),
    ("reading_order", "flash", "deepseek", 0.094313, 721, 1638, 0.398657),
    ("reading_order", "flash", "glm", 0.059639, 721, 1638, 0.413919),
    ("reading_order", "glm", "ovis", 0.361976, 931, 1638, 0.362637),
    ("reading_order", "glm", "opus", 0.287863, 931, 1638, 0.404762),
    ("reading_order", "glm", "flash", 0.271751, 931, 1638, 0.413919),
    ("reading_order", "glm", "deepseek", 0.265306, 931, 1638, 0.417582),
    ("reading_order", "glm", "paddle", 0.261010, 931, 1638, 0.420024),
    ("reading_order", "opus", "ovis", 0.236878, 743, 1638, 0.346154),
    ("reading_order", "opus", "paddle", 0.184388, 743, 1638, 0.369963),
    ("reading_order", "opus", "deepseek", 0.157470, 743, 1638, 0.382173),
    ("reading_order", "opus", "flash", 0.150740, 743, 1638, 0.385226),
    ("reading_order", "opus", "glm", 0.107672, 743, 1638, 0.404762),
    ("reading_order", "ovis", "opus", 0.081037, 617, 1638, 0.346154),
    ("reading_order", "ovis", "flash", 0.053485, 617, 1638, 0.356532),
    ("reading_order", "ovis", "paddle", 0.053485, 617, 1638, 0.356532),
    ("reading_order", "ovis", "deepseek", 0.042139, 617, 1638, 0.360806),
    ("reading_order", "ovis", "glm", 0.037277, 617, 1638, 0.362637),
    ("reading_order", "paddle", "ovis", 0.188889, 720, 1638, 0.356532),
    ("reading_order", "paddle", "opus", 0.158333, 720, 1638, 0.369963),
    ("reading_order", "paddle", "flash", 0.147222, 720, 1638, 0.374847),
    ("reading_order", "paddle", "deepseek", 0.119444, 720, 1638, 0.387057),
    ("reading_order", "paddle", "glm", 0.044444, 720, 1638, 0.420024),
)

MEASURED_RESCUES: tuple[RescueMeasurement, ...] = tuple(
    RescueMeasurement(ParseElement(element), baseline, peer, rate, wrong, pages, both)
    for element, baseline, peer, rate, wrong, pages, both in _MEASURED_ROWS
)

#: Arena model keys that this router can actually dispatch to. ``deepseek``,
#: ``glm`` and ``opus`` were measured and are deliberately absent: glm_ocr stayed
#: reference-only, opus5 is a hosted subscription rather than a self-hosted route
#: and carries its own external-transfer consent, and deepseek never wins a
#: column. Their rows stay in MEASURED_RESCUES so the evidence is whole; a future
#: route only has to appear here.
ARENA_MODEL_ROUTES: dict[str, Route] = {
    "paddle": Route.PADDLE_VL,
    "ovis": Route.OVIS_VL,
    "flash": Route.INFINITY_FLASH,
}

ROUTE_ARENA_MODELS: dict[Route, str] = {route: model for model, route in ARENA_MODEL_ROUTES.items()}


def dominant_element(page: PageMetrics) -> ParseElement:
    """Which element decides the second reader for this page.

    Compares measured densities against each other rather than against a cut-off,
    so nothing here depends on an uncalibrated threshold. A page with neither
    formula nor table content is a text page; ties go to the table, which is the
    element with the larger both-wrong floor of the two.

    Reading order is never returned: it is a property of a whole page rather than
    a region of it, and the study scored it on a different page set. It stays in
    the table for a caller that asks for it by name.
    """
    if page.formula_density <= 0.0 and page.table_density <= 0.0:
        return ParseElement.TEXT
    if page.formula_density > page.table_density:
        return ParseElement.FORMULA
    return ParseElement.TABLE


def rescues_for(baseline: Route, element: ParseElement) -> tuple[RescueMeasurement, ...]:
    """Every measured rescuer of ``baseline`` on ``element``, strongest first."""
    baseline_model = ROUTE_ARENA_MODELS.get(baseline)
    if baseline_model is None:
        return ()
    return tuple(
        row for row in MEASURED_RESCUES if row.element is element and row.baseline == baseline_model
    )


def select_cross_check_peer(
    *,
    baseline: Route,
    element: ParseElement,
    ready_routes: frozenset[Route],
) -> RescueMeasurement | None:
    """The best measured second reader that is actually servable, or nothing.

    Returns ``None`` -- and the caller must treat that as "no second read" rather
    than "any second read" -- when the baseline was never measured, when no peer
    has a route, or when every measured peer is unavailable. There is no default
    partner: a second reader chosen without evidence is a guess presented as a
    check.
    """
    for row in rescues_for(baseline, element):
        peer_route = ARENA_MODEL_ROUTES.get(row.peer)
        if peer_route is None or peer_route == baseline:
            continue
        if peer_route not in ready_routes:
            continue
        if row.rescue_rate <= 0.0:
            continue
        return row
    return None


__all__ = [
    "ARENA_MODEL_ROUTES",
    "COMPLEMENTARITY_ARTIFACT",
    "COMPLEMENTARITY_SHA256",
    "MEASURED_RESCUES",
    "ORACLE_ARTIFACT",
    "ORACLE_SHA256",
    "ROUTE_ARENA_MODELS",
    "WRONG_EDIT_THRESHOLD",
    "ParseElement",
    "RescueMeasurement",
    "dominant_element",
    "rescues_for",
    "select_cross_check_peer",
]
