"""Keyed identity for connector-declared fact keys (WO-D12-12, ADR-010) and F-D12-5.

F-D12-5, the class: two regions of one document that share an anchor (the native object id,
else the region id) name one region; they are refused by name when the document is built,
not at block construction with an unnamed error.

Keyed identity, the class: for a document of a declared connector, a unit is only ever paired
with the previous unit that carries its own key, by the unchanged matcher in a 1x1 call, and the
diff reports exactly that decision. Every test below goes through `ProductCoreCompiler.compile`
on synthetic SEC-shaped rows (no corpus) and, where a verdict is named, the unchanged U06 judge.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import akc_product_core.fact_keys as fact_keys
import pytest
from akc_cir.identity import assign_one_to_one
from akc_cir.models import BlockType
from akc_product_core.api import ProductCoreService, create_product_core_app
from akc_product_core.compiler import ProductCoreCompiler
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileRequest,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreRegion,
)
from akc_product_core.fact_keys import (
    _IDENTIFIER,
    _POSITIONAL_PROBES,
    SEC_FSDS_COLLISION_SUFFIX,
    SEC_FSDS_KEY_PATTERN,
    FactKeyDeclaration,
    FactKeyDisagreement,
)
from pydantic import ValidationError

from benchmark.u06_equivalence.harness import _digest, _request, judge

AT = datetime(2026, 1, 1, tzinfo=UTC)
ANCHOR_REFUSAL = "region anchors .*must be unique within a document"
RELEASE = "sha256:" + "a" * 64
STEP0_KEYED_SHA256 = "292ee657498e850785acda46e464f7f24e2d47936bf0d533689d5f0ee00dd83c"
SEC = FactKeyDeclaration(
    connector_type="sec-fsds",
    key_pattern=SEC_FSDS_KEY_PATTERN,
    collision_suffix=SEC_FSDS_COLLISION_SUFFIX,
    evidence_ref="receipts/WO-D12-12/step0/keyed.json",
    evidence_sha256=STEP0_KEYED_SHA256,
)
OTHER = FactKeyDeclaration(
    connector_type="other-connector",
    key_pattern=SEC_FSDS_KEY_PATTERN,
    collision_suffix=None,
    evidence_ref="test",
    evidence_sha256="0" * 64,
)
TITLE = "100 IS (template-rendered from FSDS)"
REV_Q1 = "Revenues-20240331m-1-USD"
REV_Q2 = "Revenues-20240630m-1-USD"
NET_Q1 = "NetIncomeLoss-20240331m-1-USD"
NET_Q2 = "NetIncomeLoss-20240630m-1-USD"


def _row(label: str, value: int, end: str, quarters: int = 1) -> str:
    return (
        f"{label}: {value} USD, period ending {end[:4]}-{end[4:6]} "
        f"(month as rounded by FSDS), {quarters} quarters."
    )


def _region(order: int, region_id: str, native: str | None, text: str) -> ProductCoreRegion:
    return ProductCoreRegion(
        region_id=region_id,
        page_index0=0,
        page_number1=1,
        order=order,
        text=text,
        native_object_id=native,
        authority="official",
    )


def _document(regions: tuple[ProductCoreRegion, ...]) -> ProductCoreDocument:
    body = "\n".join(region.text for region in regions)
    return ProductCoreDocument(
        native_id="doc-1",
        connector_type="synthetic",
        immutable_object_key="syn/v1/doc-1.json",
        ocr_object_key="syn/v1/doc-1.txt",
        content_sha256="sha256:" + hashlib.sha256(body.encode()).hexdigest(),
        title="Synthetic statement",
        source_filename="doc-1.json",
        page_count=1,
        regions=regions,
    )


def _sec(
    parts: Sequence[tuple[str | None, str]],
    *,
    title: str = TITLE,
    pages: dict[str, int] | None = None,
    block_types: dict[str, BlockType] | None = None,
) -> ProductCoreDocument:
    """One SEC-shaped statement; a part's key None is a region without a native id."""
    pages = pages or {}
    regions = tuple(
        ProductCoreRegion(
            region_id=key or f"region-{order}",
            page_index0=pages.get(key or "", 1) - 1,
            page_number1=pages.get(key or "", 1),
            order=order,
            block_type=(block_types or {}).get(key or "", BlockType.PARAGRAPH),
            text=text,
            native_object_id=key,
            authority="official",
        )
        for order, (key, text) in enumerate(parts)
    )
    body = "\n".join(f"{r.page_number1}|{r.block_type}|{r.region_id}|{r.text}" for r in regions)
    body += title
    return ProductCoreDocument(
        native_id="100-IS",
        connector_type="sec-fsds",
        immutable_object_key="sec-fsds/v/100-IS.json",
        ocr_object_key="sec-fsds/v/100-IS.txt",
        content_sha256="sha256:" + hashlib.sha256(body.encode()).hexdigest(),
        title=title,
        source_filename="100-IS.json",
        page_count=max([1, *pages.values()]),
        regions=regions,
    )


def _compiler(
    mode: str = "off", declarations: tuple[FactKeyDeclaration, ...] = ()
) -> ProductCoreCompiler:
    return ProductCoreCompiler(
        core_release_digest=RELEASE,
        fact_key_mode=mode,  # type: ignore[arg-type]
        fact_key_declarations=declarations,
    )


def _keyed() -> ProductCoreCompiler:
    return _compiler("candidate", (SEC,))


def _req(
    documents: list[ProductCoreDocument], previous: PreviousWorldSnapshot | None = None
) -> ProductCoreCompileRequest:
    return _request(
        documents,
        request_id="req-keys",
        previous=previous,
        requested_at=AT,
        tenant_id="tenant-foundation-pilot",
        workspace_id="workspace-foundation-pilot",
        collection_id="collection-fact-keys",
    )


def _run(
    compiler: ProductCoreCompiler,
    documents: list[ProductCoreDocument],
    previous: PreviousWorldSnapshot | None = None,
) -> ProductCoreCompileResponse:
    request = _req(documents, previous)
    return compiler.compile(request, input_sha256=_digest(request))


def _snap(response: ProductCoreCompileResponse) -> PreviousWorldSnapshot:
    return PreviousWorldSnapshot(
        world_state_id=response.candidate.world_state_id,
        manifest_digest=response.candidate.manifest_digest,
        units=response.candidate.units,
        artifact_hashes=response.candidate.artifact_hashes,
    )


def _pair(
    compiler: ProductCoreCompiler, before: ProductCoreDocument, after: ProductCoreDocument
) -> tuple[ProductCoreCompileResponse, ProductCoreCompileResponse, ProductCoreCompileResponse]:
    """(first, incremental, cold): the U06 arrangement, with this compiler on every compile."""
    first = _run(compiler, [before])
    return first, _run(compiler, [after], _snap(first)), _run(compiler, [after])


def _units(response: ProductCoreCompileResponse) -> dict[str, tuple[str, str]]:
    return {u.anchor: (u.identity_state, u.logical_id) for u in response.candidate.units}


def _changes(response: ProductCoreCompileResponse) -> list[dict[str, object]]:
    return [dict(c) for c in response.candidate.diff["changes"]]  # type: ignore[attr-defined]


def _kinds(response: ProductCoreCompileResponse) -> Counter[str]:
    return Counter(str(c["kind"]) for c in _changes(response))


def _reasons(response: ProductCoreCompileResponse, prefix: str) -> list[str]:
    return [r for r in response.candidate.review_reasons if r.startswith(prefix)]


# --------------------------------------------------------------------------- F-D12-5


def test_two_regions_with_one_native_id_are_refused_by_name() -> None:
    # Before: the document was accepted and the compile failed at CanonicalDocument with an
    # unnamed "block IDs must be unique".
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL) as raised:
        _document(
            (
                _region(0, "r-1", "Fact-1", "Net income was 100."),
                _region(1, "r-2", "Fact-1", "Revenue was 900."),
            )
        )
    assert "Net income" not in str(raised.value) and "Revenue" not in str(raised.value)


def test_a_native_id_equal_to_another_regions_region_id_is_refused() -> None:
    # The same class: the anchor is native_object_id or region_id, so these two collide too.
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL):
        _document(
            (
                _region(0, "r-1", None, "Net income was 100."),
                _region(1, "r-2", "r-1", "Revenue was 900."),
            )
        )


def test_the_served_request_contract_refuses_it_too() -> None:
    document = _document((_region(0, "r-1", "Fact-1", "Net income was 100."),))
    payload = _request(
        [document],
        request_id="req-dup",
        requested_at=AT,
        tenant_id="tenant-foundation-pilot",
        workspace_id="workspace-foundation-pilot",
        collection_id="collection-dup",
    ).model_dump(mode="json", by_alias=True)
    region = dict(payload["documents"][0]["regions"][0])
    payload["documents"][0]["regions"] = [
        region,
        {**region, "regionId": "r-2", "order": 1, "text": "Revenue was 900."},
    ]
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL):
        ProductCoreCompileRequest.model_validate(payload)


def test_distinct_anchors_still_build() -> None:
    document = _document(
        (
            _region(0, "r-1", "Fact-1", "Net income was 100."),
            _region(1, "r-2", None, "Revenue was 900."),
        )
    )
    assert [r.native_object_id or r.region_id for r in document.regions] == ["Fact-1", "r-2"]


# --------------------------------------------------------------------------- declarations, modes

ROLL_BEFORE = _sec(
    [(REV_Q1, _row("Revenues", 1000, "20240331")), (NET_Q1, _row("Net income", 100, "20240331"))]
)
ROLL_AFTER = _sec(
    [(REV_Q2, _row("Revenues", 1100, "20240630")), (NET_Q2, _row("Net income", 120, "20240630"))]
)


def test_the_pinned_pattern_takes_sec_keys_and_refuses_the_dup_fault_suffix() -> None:
    # D12-D12b: Step 0's pattern accepted "...-USD-dup"; the pinned one does not.
    step0 = r"[A-Za-z0-9._:-]+-\d{8}m-\d+-[A-Za-z0-9._:-]+"
    assert re.fullmatch(step0, "Revenues-20240331m-1-USD-dup")
    assert SEC.is_key("Revenues-20240331m-1-USD")
    assert SEC.is_key("EarningsPerShareBasic-20240331m-4-USD-shares-l12")
    assert not SEC.is_key("Revenues-20240331m-1-USD-dup")
    assert not SEC.is_key("Revenues-20240331m-1-USD-shares-dup")
    assert not SEC.is_key(None)
    assert not SEC.is_key("docx-body-p-000001")


def test_positional_probes_are_identifiers_and_a_pattern_taking_one_is_refused() -> None:
    assert all(_IDENTIFIER.fullmatch(probe) for probe in _POSITIONAL_PROBES)
    for pattern in (r"docx-body-p-\d+", r"\d+\.\d+_p\d+", r"[A-Za-z0-9._:-]+"):
        with pytest.raises(ValueError, match="positional ids"):
            FactKeyDeclaration("x-conn", pattern, None, "ref", "0" * 64)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (("", SEC_FSDS_KEY_PATTERN, None, "ref", "0" * 64), "connector_type"),
        (("bad/conn", SEC_FSDS_KEY_PATTERN, None, "ref", "0" * 64), "connector_type"),
        (("c", "", None, "ref", "0" * 64), "key_pattern"),
        (("c", "([", None, "ref", "0" * 64), "key_pattern"),
        (("c", SEC_FSDS_KEY_PATTERN, "(", "ref", "0" * 64), "collision_suffix"),
        (("c", SEC_FSDS_KEY_PATTERN, None, " ", "0" * 64), "evidence_ref"),
        (("c", SEC_FSDS_KEY_PATTERN, None, "ref", "0" * 63), "evidence_sha256"),
        (("c", SEC_FSDS_KEY_PATTERN, None, "ref", "A" * 64), "evidence_sha256"),
        (("c", None, None, "ref", "0" * 64), "key_pattern"),
    ],
)
def test_a_malformed_declaration_is_refused(fields: tuple[object, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FactKeyDeclaration(*fields)  # type: ignore[arg-type]


def test_mode_and_declarations_are_checked_at_construction() -> None:
    with pytest.raises(ValueError, match="needs at least one declaration"):
        _compiler("candidate")
    with pytest.raises(ValueError, match="off or candidate"):
        _compiler("shadow", (SEC,))
    with pytest.raises(ValueError, match="FactKeyDeclaration"):
        _compiler("candidate", ("sec-fsds",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="more than once"):
        _compiler("candidate", (SEC, SEC))
    assert _compiler().fact_key_mode == "off"


def test_off_is_byte_identical_with_and_without_declarations() -> None:
    plain, declared = _compiler(), _compiler("off", (SEC,))
    for before, after in ((ROLL_BEFORE, ROLL_AFTER),):
        a, b = _pair(plain, before, after), _pair(declared, before, after)
        for left, right in zip(a, b, strict=True):
            assert left.receipt.output_sha256 == right.receipt.output_sha256
            assert left.model_dump_json() == right.model_dump_json()
    assert a[1].receipt.matching_policy == "legacy"


def test_candidate_on_an_undeclared_connector_is_off_but_for_the_label() -> None:
    # S7: the compiler declares another connector, the document's connector is undeclared.
    off = _pair(_compiler(), ROLL_BEFORE, ROLL_AFTER)
    candidate = _pair(_compiler("candidate", (OTHER,)), ROLL_BEFORE, ROLL_AFTER)
    for left, right in zip(off, candidate, strict=True):
        assert _units(left) == _units(right)
        assert left.candidate.diff == right.candidate.diff
        assert left.candidate.review_reasons == right.candidate.review_reasons
        assert right.receipt.matching_policy == "fact_key_v1"
        assert right.candidate.validation["matchingPolicy"] == "fact_key_v1"
        metadata = right.candidate.canonical_documents[0]["metadata"]
        assert isinstance(metadata, dict) and metadata["matchingPolicy"] == "fact_key_v1"


def test_a_cold_compile_is_identical_in_both_modes_but_for_the_label() -> None:
    off, keyed = _run(_compiler(), [ROLL_AFTER]), _run(_keyed(), [ROLL_AFTER])
    assert _units(off) == _units(keyed)
    assert off.candidate.diff == keyed.candidate.diff
    assert off.candidate.review_reasons == keyed.candidate.review_reasons


def test_the_served_app_and_api_cannot_set_the_mode() -> None:
    for factory in (create_product_core_app, ProductCoreService.__init__):
        assert not any("fact_key" in name for name in inspect.signature(factory).parameters)
    service = ProductCoreService(hmac_secret=b"s" * 32, core_release_digest=RELEASE)
    assert service.compiler.fact_key_mode == "off"
    assert service.compiler._fact_keys == {}
    main = Path(inspect.getfile(ProductCoreService)).with_name("__main__.py")
    assert "fact_key" not in main.read_text(encoding="utf-8")
    payload = _req([ROLL_AFTER]).model_dump(mode="json", by_alias=True)
    ProductCoreCompileRequest.model_validate(payload)
    for field in ("factKeyMode", "factKeyDeclarations"):
        with pytest.raises(ValidationError):
            ProductCoreCompileRequest.model_validate({**payload, field: "candidate"})


# --------------------------------------------------------------------------- keyed outcomes


def test_a_period_roll_over_is_removed_plus_added_not_a_modification() -> None:
    # Today (off): the new period's row inherits the vanished period's id, MODIFIED_CLAIM.
    first, legacy, _ = _pair(_compiler(), ROLL_BEFORE, ROLL_AFTER)
    old = {u.logical_id: u.anchor for u in first.candidate.units}
    assert {a: old.get(lid) for a, (_, lid) in _units(legacy).items()} == {
        REV_Q2: REV_Q1,
        NET_Q2: NET_Q1,
    }
    assert _kinds(legacy)["modified_claim"] == 2

    first, inc, cold = _pair(_keyed(), ROLL_BEFORE, ROLL_AFTER)
    old_ids = {u.logical_id for u in first.candidate.units}
    assert {state for state, _ in _units(inc).values()} == {"new"}
    assert not old_ids & {lid for _, lid in _units(inc).values()}
    assert _kinds(inc) == Counter({"unit_added": 2, "unit_removed": 2})
    removed = {c["logical_id"] for c in _changes(inc) if c["kind"] == "unit_removed"}
    assert removed == old_ids
    assert inc.receipt.equivalence == "passed"
    assert judge(inc, cold).verdict == "EQUAL"
    assert inc.receipt.matching_policy == "fact_key_v1"


def test_a_restatement_under_one_key_is_matched_and_modified() -> None:
    before = _sec([(REV_Q1, _row("Revenues", 1000, "20240331"))])
    after = _sec([(REV_Q1, _row("Revenues", 1050, "20240331"))])
    first, inc, cold = _pair(_keyed(), before, after)
    assert _units(inc) == {REV_Q1: ("matched", first.candidate.units[0].logical_id)}
    assert _kinds(inc) == Counter({"modified_claim": 1, "evidence_moved": 1})
    assert judge(inc, cold).verdict == "EQUAL"


def test_one_key_carrying_unrelated_text_is_held_and_its_previous_unit_not_removed() -> None:
    before = _sec([(REV_Q1, _row("Revenues", 1000, "20240331"))])
    after = _sec([(REV_Q1, "Total liabilities and equity at year end were restated.")])
    first, inc, cold = _pair(_keyed(), before, after)
    assert _units(inc)[REV_Q1][0] == "unresolved"
    unresolved = [c for c in _changes(inc) if c["kind"] == "identity_unresolved"]
    assert [c["candidates"] for c in unresolved] == [[first.candidate.units[0].logical_id]]
    assert _kinds(inc)["unit_removed"] == 0
    assert judge(inc, cold).hold_reasons == ("IDENTITY_UNRESOLVED",)


def test_a_short_row_restatement_is_held_by_the_band() -> None:
    # The price of the band (D12-D12a): "Revenues: 1000 USD." -> "1200" is not similar enough.
    before, after = _sec([(REV_Q1, "Revenues: 1000 USD.")]), _sec([(REV_Q1, "Revenues: 1200 USD.")])
    _, inc, _ = _pair(_keyed(), before, after)
    assert _units(inc)[REV_Q1][0] == "unresolved"
    assert _kinds(inc)["identity_unresolved"] == 1


def test_a_page_move_under_one_key_is_held_even_with_identical_text() -> None:
    # D12-D12a: same key, same text, page 1 -> 2: the structural path drops, AMBIGUOUS.
    parts = [
        (REV_Q1, _row("Revenues", 1000, "20240331")),
        (NET_Q1, _row("Net income", 100, "20240331")),
    ]
    _, inc, _ = _pair(_keyed(), _sec(parts), _sec(parts, pages={REV_Q1: 2}))
    assert _units(inc)[REV_Q1][0] == "unresolved"
    assert _units(inc)[NET_Q1][0] == "matched"
    assert _kinds(inc)["identity_unresolved"] == 1 and _kinds(inc)["unit_removed"] == 0


def test_a_block_type_change_under_one_key_is_held_even_with_identical_text() -> None:
    # D12-D12a: paragraph -> list, same key, same text: the path's last part differs, AMBIGUOUS.
    parts = [
        (REV_Q1, _row("Revenues", 1000, "20240331")),
        (NET_Q1, _row("Net income", 100, "20240331")),
    ]
    _, inc, _ = _pair(_keyed(), _sec(parts), _sec(parts, block_types={REV_Q1: BlockType.LIST}))
    assert _units(inc)[REV_Q1][0] == "unresolved"
    assert _units(inc)[NET_Q1][0] == "matched"
    assert _kinds(inc)["identity_unresolved"] == 1 and _kinds(inc)["unit_removed"] == 0


def test_a_title_change_splits_every_keyed_fact() -> None:
    # D12-D12a: same keys, same texts, new title: NEW + REMOVED per key, and the two sides agree.
    parts = [
        (REV_Q1, _row("Revenues", 1000, "20240331")),
        (NET_Q1, _row("Net income", 100, "20240331")),
    ]
    first, inc, cold = _pair(_keyed(), _sec(parts), _sec(parts, title="100 IS restated"))
    assert {state for state, _ in _units(inc).values()} == {"new"}
    removed = {c["logical_id"] for c in _changes(inc) if c["kind"] == "unit_removed"}
    assert removed == {u.logical_id for u in first.candidate.units}
    assert _kinds(inc)["unit_added"] == 2 and _kinds(inc)["modified_claim"] == 0
    assert inc.receipt.equivalence == "passed" and judge(inc, cold).verdict == "EQUAL"


def test_a_mixed_document_takes_todays_path_and_says_why() -> None:
    before = _sec([(REV_Q1, _row("Revenues", 1000, "20240331")), (None, "Free text note.")])
    after = _sec([(REV_Q2, _row("Revenues", 1100, "20240630")), (None, "Free text note.")])
    legacy = _pair(_compiler(), before, after)[1]
    _, inc, _ = _pair(_keyed(), before, after)
    assert _units(inc) == _units(legacy)
    assert inc.candidate.diff == legacy.candidate.diff
    assert _reasons(inc, "IDENTITY_FACT_KEY_REFUSED:") == [
        f"IDENTITY_FACT_KEY_REFUSED:{inc.candidate.units[0].source_id}:D-MISSING"
    ]


def test_a_previous_anchor_that_is_not_an_identifier_refuses_the_document() -> None:
    # Hostile previous world: anchors are unbounded str on the wire; a keyed anchor must be an id.
    first = _run(_keyed(), [ROLL_BEFORE])
    forged = _snap(first)
    long_key = "Revenues-20240331m-1-" + "U" * 300
    forged = forged.model_copy(
        update={
            "units": (forged.units[0].model_copy(update={"anchor": long_key}), *forged.units[1:])
        }
    )
    inc = _run(_keyed(), [ROLL_AFTER], forged)
    assert [r.rsplit(":", 1)[1] for r in _reasons(inc, "IDENTITY_FACT_KEY_REFUSED:")] == [
        "D-MISSING"
    ]
    assert not any(long_key in r for r in inc.candidate.review_reasons)


@pytest.mark.parametrize(
    ("before_keys", "after_keys"),
    [
        # collision suffix: "X" and "X-l12" in one version
        ([REV_Q1, NET_Q1], [REV_Q1, REV_Q1 + "-l12"]),
        # fold inside one version: "." and "-" fold alike
        ([REV_Q1, NET_Q1], ["Rev.A-20240331m-1-USD", "Rev-A-20240331m-1-USD"]),
        # fold across versions (N1): same key, other raw spelling
        (["Rev.A-20240331m-1-USD", NET_Q1], ["Rev-A-20240331m-1-USD", NET_Q1]),
        # fold where the suffix strips on one spelling only ("-l3" vs "-L3")
        ([REV_Q1, NET_Q1], ["Rev-A-20240331m-1-USD-l3", "rev-a-20240331m-1-usd-L3"]),
        # suffix plus fold: "X-l12" and "x"
        ([NET_Q1, NET_Q2], [REV_Q1 + "-l12", REV_Q1.lower()]),
    ],
    ids=["suffix", "fold-within", "fold-across", "fold-with-suffix", "suffix-fold"],
)
def test_duplicate_keys_refuse_the_document(before_keys: list[str], after_keys: list[str]) -> None:
    before = _sec([(k, _row(f"Line {i}", 10 + i, "20240331")) for i, k in enumerate(before_keys)])
    after = _sec([(k, _row(f"Line {i}", 20 + i, "20240331")) for i, k in enumerate(after_keys)])
    legacy = _pair(_compiler(), before, after)[1]
    _, inc, _ = _pair(_keyed(), before, after)
    assert [r.rsplit(":", 1)[1] for r in _reasons(inc, "IDENTITY_FACT_KEY_REFUSED:")] == ["D-DUP"]
    assert _units(inc) == _units(legacy)


def test_the_dup_fault_on_a_declared_document_is_equal_or_hold() -> None:
    # D12-D12b: the U06 duplicate_region_text fault appends "-dup"; the pinned pattern refuses it,
    # so the document stays on today's path, which holds identical text.
    text = _row("Revenues", 1000, "20240331")
    before = _sec([(REV_Q1, text), (NET_Q1, _row("Net income", 100, "20240331"))])
    after = _sec(
        [(REV_Q1, text), (NET_Q1, _row("Net income", 100, "20240331")), (REV_Q1 + "-dup", text)]
    )
    _, inc, cold = _pair(_keyed(), before, after)
    assert [r.rsplit(":", 1)[1] for r in _reasons(inc, "IDENTITY_FACT_KEY_REFUSED:")] == [
        "D-MISSING"
    ]
    assert judge(inc, cold).verdict in ("EQUAL", "HOLD")


def test_rotated_keys_are_recorded_per_unit_and_decided_per_key() -> None:
    # A wrong declaration's signature: every text moves one key down. D-RELOC records each unit
    # (D12-D12, K-unit) and refuses nothing; each key is then decided against its own past.
    keys = [f"Line{i}-20240331m-1-USD" for i in range(3)]
    texts = [_row(f"Line item {i}", 100 * (i + 1), "20240331") for i in range(3)]
    before = _sec(list(zip(keys, texts, strict=True)))
    after = _sec(list(zip(keys, texts[1:] + texts[:1], strict=True)))
    first, inc, cold = _pair(_keyed(), before, after)
    source = inc.candidate.units[0].source_id
    assert sorted(_reasons(inc, "IDENTITY_FACT_KEY_RELOCATED:")) == sorted(
        f"IDENTITY_FACT_KEY_RELOCATED:{source}:{keys[(i + 1) % 3]}->{keys[i]}" for i in range(3)
    )
    old = {u.logical_id: u.anchor for u in first.candidate.units}
    # Pinned outcome: similar rows under one key pass the band, so the key's id continues (a
    # merge the key asserts; the relocation reasons are what a reader sees).
    assert {a: (s, old.get(lid)) for a, (s, lid) in _units(inc).items()} == {
        k: ("matched", k) for k in keys
    }
    assert _kinds(inc)["modified_claim"] == 3
    assert judge(inc, cold).verdict == "EQUAL"


def test_renumbered_keys_with_edits_are_pinned() -> None:
    # Renumbering with edits: the reworded text is no longer exact, so D-RELOC cannot see it.
    before = _sec([("A1-20240331m-1-USD", _row("Line item one", 100, "20240331"))])
    after = _sec([("A2-20240331m-1-USD", _row("Line item one restated", 105, "20240331"))])
    _, inc, _ = _pair(_keyed(), before, after)
    assert _reasons(inc, "IDENTITY_FACT_KEY_RELOCATED:") == []
    assert _units(inc)["A2-20240331m-1-USD"][0] == "new"
    assert _kinds(inc) == Counter({"unit_added": 1, "unit_removed": 1})


def test_regenerated_keys_remove_and_add_every_unit_and_record_each() -> None:
    # Churn: every key replaced, texts kept. K-unit: no refusal; every unit recorded.
    texts = [_row(f"Line item {i}", 100 + i, "20240331") for i in range(3)]
    old_keys = [f"Old{i}-20240331m-1-USD" for i in range(3)]
    new_keys = [f"New{i}-20240331m-1-USD" for i in range(3)]
    before = _sec(list(zip(old_keys, texts, strict=True)))
    after = _sec(list(zip(new_keys, texts, strict=True)))
    _, inc, cold = _pair(_keyed(), before, after)
    assert len(_reasons(inc, "IDENTITY_FACT_KEY_RELOCATED:")) == 3
    assert {s for s, _ in _units(inc).values()} == {"new"}
    assert _kinds(inc) == Counter({"unit_added": 3, "unit_removed": 3})
    assert judge(inc, cold).verdict == "EQUAL"


def test_a_key_reused_for_another_fact_is_pinned() -> None:
    # Key B now carries fact A's text and A is gone. B is decided against B's own past text.
    a, b = "A-20240331m-1-USD", "B-20240331m-1-USD"
    text_a = _row("Revenues", 1000, "20240331")
    text_b = "Shares outstanding at period end: 52 million."
    first, inc, _ = _pair(_keyed(), _sec([(a, text_a), (b, text_b)]), _sec([(b, text_a)]))
    source = inc.candidate.units[0].source_id
    assert _reasons(inc, "IDENTITY_FACT_KEY_RELOCATED:") == [
        f"IDENTITY_FACT_KEY_RELOCATED:{source}:{a}->{b}"
    ]
    assert _units(inc)[b][0] == "unresolved"
    a_id = {u.anchor: u.logical_id for u in first.candidate.units}[a]
    assert [c["logical_id"] for c in _changes(inc) if c["kind"] == "unit_removed"] == [a_id]


def test_an_unchanged_document_takes_todays_path() -> None:
    parts = [(REV_Q1, _row("Revenues", 1000, "20240331"))]
    legacy = _pair(_compiler(), _sec(parts), _sec(parts))[1]
    inc = _pair(_keyed(), _sec(parts), _sec(parts))[1]
    assert _units(inc) == _units(legacy) and inc.candidate.diff == legacy.candidate.diff
    assert _kinds(inc) == Counter({"content_unchanged": 1})


# --------------------------------------------------------------------------- switch, agreement


def test_three_versions_off_off_candidate_continue_ids_under_the_current_key() -> None:
    # S6: v2 (off) merges the roll-over across keys, so REV_Q2 carries REV_Q1's seed id.
    off = _compiler()
    v1 = _run(off, [_sec([(REV_Q1, _row("Revenues", 1000, "20240331"))])])
    v2 = _run(off, [_sec([(REV_Q2, _row("Revenues", 1100, "20240630"))])], _snap(v1))
    seed_q1 = v1.candidate.units[0].logical_id
    assert _units(v2) == {REV_Q2: ("matched", seed_q1)}

    # (a) v3 keeps REV_Q2 and brings REV_Q1 back: REV_Q2 keeps its id; REV_Q1's seed is taken.
    v3 = _run(
        _keyed(),
        [
            _sec(
                [
                    (REV_Q2, _row("Revenues", 1100, "20240630")),
                    (REV_Q1, _row("Revenues", 990, "20240331")),
                ]
            )
        ],
        _snap(v2),
    )
    units = _units(v3)
    assert units[REV_Q2] == ("matched", seed_q1)
    assert units[REV_Q1][0] == "unresolved" and units[REV_Q1][1].startswith("ku_unresolved_")

    # (b) v3 drops REV_Q2 and brings REV_Q1 back: no current unit holds the id, D-SEED holds it.
    v3b = _run(_keyed(), [_sec([(REV_Q1, _row("Revenues", 990, "20240331"))])], _snap(v2))
    assert _units(v3b)[REV_Q1][0] == "unresolved"
    assert [c["logical_id"] for c in _changes(v3b) if c["kind"] == "unit_removed"] == [seed_q1]
    added = [c["logical_id"] for c in _changes(v3b) if c["kind"] == "unit_added"]
    assert seed_q1 not in added
    assert any(r.startswith("IDENTITY_AMBIGUOUS:") for r in v3b.candidate.review_reasons)


def test_a_compiler_and_diff_disagreement_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # S3: force the compiler's per-key matcher to see no previous unit while the diff still does.
    monkeypatch.setattr(
        fact_keys,
        "assign_one_to_one",
        lambda incoming, previous, **kw: assign_one_to_one(incoming, []),
    )
    before = _sec([(REV_Q1, _row("Revenues", 1000, "20240331"))])
    after = _sec([(REV_Q1, _row("Revenues secret figure", 1050, "20240331"))])
    first = _run(_keyed(), [before])
    with pytest.raises(FactKeyDisagreement) as raised:
        _run(_keyed(), [after], _snap(first))
    assert isinstance(raised.value, ValueError)
    assert raised.value.key == REV_Q1 and raised.value.decision == "new"
    assert "secret" not in str(raised.value) and "Revenues:" not in str(raised.value)


def _table(n: int) -> tuple[ProductCoreDocument, ProductCoreDocument]:
    """n rows, five operations in turn, plus n // 10 new keys: unchanged, restated, rolled over,
    removed, and same key with unrelated text."""
    before, after = [], []
    for i in range(n):
        key, label = f"Tag{i:03d}-20240331m-1-USD", f"Line item {i:03d}"
        text = _row(label, 1000 + i, "20240331")
        before.append((key, text))
        op = i % 5
        if op == 0:
            after.append((key, text))
        elif op == 1:
            after.append((key, _row(label, 2000 + i, "20240331")))
        elif op == 2:
            after.append((f"Tag{i:03d}-20240630m-1-USD", _row(label, 1000 + i, "20240630")))
        elif op == 4:
            after.append((key, f"Unrelated disclosure number {i} about leases."))
    after += [
        (f"New{i:03d}-20240331m-1-USD", _row(f"New item {i:03d}", i, "20240331"))
        for i in range(n // 10)
    ]
    return _sec(before), _sec(after)


def test_two_hundred_mixed_rows_agree_and_keep_every_same_key_match() -> None:
    before, after = _table(200)
    first_l, legacy, _ = _pair(_compiler(), before, after)
    first_k, inc, cold = _pair(_keyed(), before, after)  # the agreement check would raise
    assert first_l.candidate.units == first_k.candidate.units
    old = {u.logical_id: u.anchor for u in first_k.candidate.units}
    keyed = _units(inc)
    # L same-key MATCHED implies K MATCHED with the same id.
    same_key = [a for a, (s, lid) in _units(legacy).items() if s == "matched" and old.get(lid) == a]
    assert same_key
    assert all(keyed[a] == _units(legacy)[a] for a in same_key)
    # No unit is paired across keys.
    assert all(old[lid] == a for a, (s, lid) in keyed.items() if s == "matched")
    states = Counter(s for s, _ in keyed.values())
    assert states == Counter({"matched": 80, "new": 60, "unresolved": 40})
    kinds = _kinds(inc)
    assert kinds["identity_unresolved"] == 40 and kinds["modified_claim"] == 40
    assert kinds["unit_removed"] == 80  # 40 rolled over + 40 removed
    assert kinds["unit_added"] == 60 + 40  # new units + quarantined unresolved candidates
    assert inc.receipt.equivalence == "passed"
    assert judge(inc, cold).hold_reasons == ("IDENTITY_UNRESOLVED",)


def test_no_logical_id_collision_on_the_keyed_path() -> None:
    before, after = _table(50)
    _, inc, _ = _pair(_keyed(), before, after)
    ids = [u.logical_id for u in inc.candidate.units]
    assert len(ids) == len(set(ids))
