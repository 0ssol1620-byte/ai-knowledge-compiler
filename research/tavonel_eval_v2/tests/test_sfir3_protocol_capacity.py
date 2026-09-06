from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))

import probe_sfir3_capacity as probe  # noqa: E402
import sfir3_protocol as protocol  # noqa: E402
import sfir3_spent_authority as spent_builder  # noqa: E402
from acquisition import sources_sfir3 as sources  # noqa: E402

STAMP = "2026-08-26T14:00:00Z"


def _isolated(root: Path) -> tuple[Path, dict[str, str]]:
    files = (
        "acquisition/sources_sfir3.py",
        "tools/probe_sfir3_capacity.py",
        "tools/sfir3_spent_authority.py",
        "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3_DESIGN_CHARTER.yaml",
    )
    for relative in files:
        target = root / "research/tavonel_eval_v2" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(NS / relative, target)
    charter_yaml = (
        root
        / "research/tavonel_eval_v2/protocols"
        / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3_DESIGN_CHARTER.yaml"
    )
    charter = root / "receipts/charter.json"
    protocol.freeze_design_charter(root, charter_yaml, charter, STAMP)
    spent = root / "receipts/spent.json"
    protocol._write_immutable(
        spent,
        {
            "schema": protocol.SPENT_AUTHORITY_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": STAMP,
            "container_ids": ["old:container"],
            "lineage_ids": ["old:lineage"],
            "alias_ids": ["old:alias"],
        },
    )
    return charter, protocol.exact_ref(root, spent)


def test_static_roots_are_disjoint_from_full_comprehensive_history() -> None:
    body = json.loads(
        (NS / "receipts/sfir2-spent-identity-authority.json").read_text(encoding="utf-8")
    )
    sources.assert_disjoint_from_comprehensive_spent(body["container_ids"], body["alias_ids"])
    assert len(sources.SOURCE_POOLS["git_docs"]["repositories"]) == 30
    assert len(sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"]) == 30
    assert sources.SOURCE_POOLS["git_docs"]["max_total_candidates"] == 30 * 80
    assert sources.SOURCE_POOLS["encyclopedia_wikipedia"]["max_total_candidates"] == 30 * 150


def test_spent_composition_reserves_git_and_wiki_but_not_unreached_ecfr(tmp_path: Path) -> None:
    refs = [
        protocol.exact_ref(REPO, NS / "receipts/sfir2-spent-identity-authority.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir2-design-charter-freeze.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir2-capacity-failure-authority.json"),
    ]
    destination = tmp_path / "sfir3-spent.json"
    spent_builder.compose_spent_authority(REPO, *refs, destination, STAMP)
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["derivation"]["failure_stage"] == "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT"
    assert body["derivation"]["exact_root_unknown"] is True
    assert body["derivation"]["families_not_reached"] == [
        "regulation_ecfr",
        "encyclopedia_wikipedia",
    ]
    assert len(body["reserved_sfir2_declared_roots"]["git_docs"]) == 30
    assert body["reserved_sfir2_declared_roots"]["encyclopedia_wikipedia"] == []
    assert body["reserved_sfir2_declared_roots"]["regulation_ecfr"] == []
    assert body["predecessor_sources"]["sfir2_terminal_failure"]["sha256"] == (
        spent_builder.SFIR2_FAILURE_SHA256
    )
    wrong = dict(refs[2])
    wrong["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(protocol.SFIR3Refused, match="authority reference missing or drifted"):
        spent_builder.compose_spent_authority(
            REPO, refs[0], refs[1], wrong, tmp_path / "must-not-write.json", STAMP
        )


def test_probe_emits_exhaustive_zero_dispositions_and_continues(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)
    calls = {family: 0 for family in sources.FAMILIES}

    def transport(family: str, request: dict) -> dict:
        index = calls[family]
        calls[family] += 1
        roots = sources.declared_roots(family)
        next_cursor = str(index + 1) if index + 1 < len(roots) else None
        return {
            "items": [],
            "next_cursor": next_cursor,
            "snapshot_id": f"zero:{family}:{index}",
            "response_refs": [f"https://metadata.invalid/{family}/{index}"],
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": request["expected_discovery_root_id"],
                "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                "reason": "HTTP_404",
            },
        }

    destination = tmp_path / "capacity.json"
    probe.probe_capacity(
        tmp_path, charter, protocol.sha_file(charter), spent, destination, transport
    )
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert calls == {family: len(sources.declared_roots(family)) for family in sources.FAMILIES}
    for family, block in body["families"].items():
        assert block["pagination"]["exhausted"] is True
        assert len(block["root_dispositions"]) == len(sources.declared_roots(family))
        assert block["candidates"] == []


def test_live_git_unavailable_and_truncated_are_zero_not_global_failure() -> None:
    pool = sources.SOURCE_POOLS["git_docs"]
    request = {
        "cursor": None,
        "pool": pool,
        "metadata_only": True,
        "expected_discovery_root_id": sources.discovery_root_id(
            "git_docs", pool["repositories"][0]
        ),
    }

    def missing(url: str):
        raise probe.RootUnavailable(404, url)

    missing_result = probe.LiveMetadataTransport(missing)("git_docs", request)
    assert missing_result["root_disposition"]["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    calls = 0

    def truncated(_url: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"default_branch": "main"}
        if calls == 2:
            return {"sha": "a" * 40}
        return {"sha": "b" * 40, "tree": [], "truncated": True}

    truncated_result = probe.LiveMetadataTransport(truncated)("git_docs", request)
    assert truncated_result["root_disposition"]["reason"] == "TRUNCATED_OR_INCOMPLETE_ENUMERATION"


def test_git_enumeration_pins_branch_once_to_immutable_head_and_tree() -> None:
    pool = sources.SOURCE_POOLS["git_docs"]
    repo = pool["repositories"][0]
    head_sha, tree_sha = "a" * 40, "b" * 40
    seen: list[str] = []

    def fetch(url: str):
        seen.append(url)
        if url.endswith(f"/repos/{repo}"):
            return {"default_branch": "main"}
        if url.endswith(f"/repos/{repo}/commits/main"):
            return {"sha": head_sha}
        if f"/git/trees/{head_sha}?recursive=1" in url:
            return {"sha": tree_sha, "tree": [{"type": "blob", "path": "docs/a.md"}]}
        assert f"sha={head_sha}" in url
        assert "sha=main" not in url
        return [
            {
                "sha": "2" * 40,
                "commit": {"committer": {"date": "2026-01-02T00:00:00Z"}},
            },
            {
                "sha": "1" * 40,
                "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}},
            },
        ]

    result = probe.LiveMetadataTransport(fetch)(
        "git_docs",
        {
            "cursor": None,
            "pool": pool,
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id("git_docs", repo),
        },
    )
    assert result["snapshot_id"] == f"github:{repo}:head:{head_sha}:tree:{tree_sha}"
    assert len(result["items"]) == 1
    assert any(f"/commits/main" in url for url in seen)


def test_ecfr_double_census_is_page_streamed_and_exact() -> None:
    pool = sources.SOURCE_POOLS["regulation_ecfr"]
    destroyed = 0
    calls = 0

    class PageRows(list):
        def __del__(self):
            nonlocal destroyed
            destroyed += 1

    def fetch(url: str):
        nonlocal calls
        calls += 1
        if calls == 3:
            assert destroyed >= 2, "prior census page lists were retained"
        page = 2 if "?page=2" in url else 1
        rows = PageRows(
            [
                {
                    "type": "section",
                    "part": "1",
                    "identifier": "1.1",
                    "date": f"2026-01-0{page}",
                    "removed": False,
                },
                {
                    "type": "section",
                    "part": "2",
                    "identifier": "2.1",
                    "date": f"2026-01-0{page}",
                    "removed": False,
                },
            ]
        )
        return {
            "content_versions": rows,
            "meta": {"total_pages": 2, "result_count": 4, "latest_date": "2026-01-02"},
        }

    result = probe.LiveMetadataTransport(fetch)(
        "regulation_ecfr",
        {
            "cursor": None,
            "pool": pool,
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id("regulation_ecfr", 1),
        },
    )
    assert calls == 4
    assert result["root_disposition"]["state"] == "COMPLETE"
    assert ":pages:2:rows:4:latest:2026-01-02:observed-sha256:" in result["snapshot_id"]
    assert len(result["response_refs"]) == 4


def test_ecfr_large_aggregate_state_is_all_or_nothing_zero(monkeypatch) -> None:
    pool = sources.SOURCE_POOLS["regulation_ecfr"]
    monkeypatch.setattr(sources, "MAX_ECFR_VERSION_AGGREGATE_STATE_BYTES", 64)

    def fetch(_url: str):
        return {
            "content_versions": [
                {
                    "type": "section",
                    "part": "1",
                    "identifier": "x" * 128,
                    "date": "2026-01-01",
                    "removed": False,
                }
            ],
            "meta": {"total_pages": 1, "result_count": 1, "latest_date": "2026-01-01"},
        }

    result = probe.LiveMetadataTransport(fetch)(
        "regulation_ecfr",
        {
            "cursor": None,
            "pool": pool,
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id("regulation_ecfr", 1),
        },
    )
    assert result["items"] == []
    assert result["root_disposition"] == {
        "discovery_root_id": sources.discovery_root_id("regulation_ecfr", 1),
        "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
        "reason": "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
    }
    assert result["response_refs"]


def test_wikipedia_second_membership_census_discards_snapshot_drift() -> None:
    pool = sources.SOURCE_POOLS["encyclopedia_wikipedia"]
    category_calls = 0

    def fetch(url: str):
        nonlocal category_calls
        if "list=categorymembers" in url:
            category_calls += 1
            title = "Stable title" if category_calls == 1 else "Changed title"
            return {"query": {"categorymembers": [{"pageid": 7, "title": title}]}}
        return {
            "query": {
                "pages": [
                    {
                        "pageid": 7,
                        "title": "Stable title",
                        "revisions": [
                            {"revid": 2, "timestamp": "2026-01-02T00:00:00Z"},
                            {"revid": 1, "timestamp": "2026-01-01T00:00:00Z"},
                        ],
                    }
                ]
            }
        }

    result = probe.LiveMetadataTransport(fetch)(
        "encyclopedia_wikipedia",
        {
            "cursor": None,
            "pool": pool,
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id(
                "encyclopedia_wikipedia", pool["category_roots"][0]
            ),
        },
    )
    assert category_calls == 2
    assert result["items"] == []
    assert result["root_disposition"]["reason"] == "SNAPSHOT_DRIFT_DURING_ENUMERATION"
    assert len(result["response_refs"]) == 3


def test_probe_refuses_malformed_or_exhausted_rate_limit(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)

    def malformed(_family: str, _request: dict) -> dict:
        return {"items": [], "next_cursor": None}

    with pytest.raises(protocol.SFIR3Refused, match="response shape malformed"):
        probe.probe_capacity(
            tmp_path,
            charter,
            protocol.sha_file(charter),
            spent,
            tmp_path / "malformed.json",
            malformed,
        )

    def limited(_family: str, request: dict) -> dict:
        return {
            "items": [],
            "next_cursor": request.get("cursor"),
            "snapshot_id": "rate",
            "response_refs": [],
            "rate_limited": True,
            "root_disposition": None,
        }

    with pytest.raises(protocol.SFIR3Refused, match="rate-limit retry budget exhausted"):
        probe.probe_capacity(
            tmp_path, charter, protocol.sha_file(charter), spent, tmp_path / "limited.json", limited
        )


def test_zero_disposition_cannot_emit_or_contribute_items(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)

    def hidden_partial(family: str, request: dict) -> dict:
        root = sources.declared_roots(family)[0]
        item = (
            {
                "repository": root,
                "path": "docs/a.md",
                "commit_before": "1" * 40,
                "commit_after": "2" * 40,
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            }
            if family == "git_docs"
            else {"partial": "metadata"}
        )
        return {
            "items": [item],
            "next_cursor": None,
            "snapshot_id": "partial:snapshot",
            "response_refs": ["https://metadata.invalid/partial"],
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": request["expected_discovery_root_id"],
                "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                "reason": "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
            },
        }

    with pytest.raises(protocol.SFIR3Refused, match="zero-candidate root emitted candidates"):
        probe.probe_capacity(
            tmp_path,
            charter,
            protocol.sha_file(charter),
            spent,
            tmp_path / "hidden-partial.json",
            hidden_partial,
        )


def test_candidate_exactly_binds_revision_and_payload_locator() -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "docs/a.md",
            "commit_before": "1" * 40,
            "commit_after": "2" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    declared = {
        sources.discovery_root_id("git_docs", value)
        for value in sources.declared_roots("git_docs")
    }
    protocol._validate_candidate("git_docs", row, declared, set())
    row["payload_ref"]["after"] = row["payload_ref"]["after"].replace("2" * 40, "3" * 40)
    with pytest.raises(protocol.SFIR3Refused, match="locator binding"):
        protocol._validate_candidate("git_docs", row, declared, set())


@pytest.mark.parametrize(
    ("before_timestamp", "after_timestamp"),
    [
        ("2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
        ("2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z"),
    ],
)
def test_git_nonmonotonic_commit_timestamps_are_deterministically_skipped(
    before_timestamp: str, after_timestamp: str
) -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    item = {
        "repository": repo,
        "path": "docs/clock-skew.md",
        "commit_before": "1" * 40,
        "commit_after": "2" * 40,
        "timestamp_before": before_timestamp,
        "timestamp_after": after_timestamp,
    }
    assert probe._candidate("git_docs", item) is None
    assert probe._candidate("git_docs", item) is None


def test_emitted_git_candidate_still_requires_strict_chronology() -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "docs/ordered.md",
            "commit_before": "1" * 40,
            "commit_after": "2" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    row["revision_timestamp"] = {
        "before": "2026-01-02T00:00:00Z",
        "after": "2026-01-02T00:00:00Z",
    }
    declared = {
        sources.discovery_root_id("git_docs", value)
        for value in sources.declared_roots("git_docs")
    }
    with pytest.raises(protocol.SFIR3Refused, match="revision chronology invalid"):
        protocol._validate_candidate("git_docs", row, declared, set())


def test_roster_order_is_bound_to_predeclared_salt(monkeypatch) -> None:
    row = {"lineage_id": "lineage:1"}
    before = protocol._candidate_order("git_docs", row)
    monkeypatch.setattr(sources, "SELECTION_SALT", "different-prospective-salt")
    assert protocol._candidate_order("git_docs", row) != before


def test_metadata_http_body_has_a_hard_stream_bound(monkeypatch) -> None:
    class Oversized:
        headers = {"Content-Length": str(sources.MAX_METADATA_RESPONSE_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *_args, **_kwargs: Oversized())
    with pytest.raises(protocol.SFIR3Refused, match="exceeds the frozen bound"):
        probe._http_json("https://api.github.com/repos/example/example")


def test_capacity_seal_independently_refuses_per_root_cap(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)
    families = {}
    for family in sources.FAMILIES:
        roots = sources.declared_roots(family)
        response_refs = [
            f"https://metadata.invalid/{family}/{index}" for index in range(len(roots))
        ]
        dispositions = [
            {
                "discovery_root_id": sources.discovery_root_id(family, root),
                "state": "COMPLETE",
                "reason": "ENUMERATION_EXHAUSTED",
                "snapshot_ref": f"snap:{family}:{index}",
                "response_refs": [response_refs[index]],
            }
            for index, root in enumerate(roots)
        ]
        families[family] = {
            "authority": sources.FAMILY_AUTHORITIES[family],
            "snapshot_refs": [row["snapshot_ref"] for row in dispositions],
            "response_refs": response_refs,
            "root_dispositions": dispositions,
            "pagination": {"pages_fetched": len(roots), "exhausted": True},
            "candidates": [],
        }
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    for index in range(81):
        made = probe._candidate(
            "git_docs",
            {
                "repository": repo,
                "path": f"docs/{index}.md",
                "commit_before": f"{index + 1:040x}",
                "commit_after": f"{index + 1001:040x}",
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            },
        )
        assert made is not None
        families["git_docs"]["candidates"].append(made[0])
    metadata = tmp_path / "capacity-input.json"
    metadata.write_text(
        json.dumps(
            {
                "schema": protocol.CAPACITY_INPUT_SCHEMA,
                "protocol_id": protocol.PROTOCOL_ID,
                "families": families,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(protocol.SFIR3Refused, match="per-root candidate cap exceeded"):
        protocol.seal_capacity_census(
            tmp_path,
            protocol.exact_ref(tmp_path, charter),
            spent,
            metadata,
            tmp_path / "capacity-authority.json",
            STAMP,
        )


def test_execution_manifest_enriched_reference_is_exact(tmp_path: Path, monkeypatch) -> None:
    import sfir3_execution

    component = tmp_path / "tools/worker.py"
    component.parent.mkdir(parents=True)
    component.write_text("# frozen worker\n", encoding="utf-8")
    body = {
        "schema": "tavonel.sfir3.execution_manifest.v1",
        "protocol_id": protocol.PROTOCOL_ID,
        "coverage": {"acquisition": True, "scoring": True},
        "components": {"worker": protocol.exact_ref(tmp_path, component)},
        "generated_at": STAMP,
    }
    body["content_digest"] = protocol.digest(body)
    manifest = tmp_path / "receipts/execution-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(body), encoding="utf-8")
    ref = {
        **protocol.exact_ref(tmp_path, manifest),
        "content_digest": body["content_digest"],
        "schema": body["schema"],
    }
    monkeypatch.setattr(sfir3_execution, "ROOT", tmp_path)
    monkeypatch.setattr(
        sfir3_execution, "execution_toolchain_manifest", lambda _generated_at: body
    )
    assert protocol.verify_execution_manifest_ref(tmp_path, ref) == body
    with pytest.raises(protocol.SFIR3Refused, match="enriched reference mismatch"):
        protocol.verify_execution_manifest_ref(
            tmp_path, {**ref, "content_digest": "sha256:" + "0" * 64}
        )


# --- INC-V2-096: an empty eCFR root is a disposition, not an abort ----------
#
# CFR title 35 is reserved. The versioner API answers 200 with `result_count: 0`,
# no `content_versions`, and a `meta` carrying only `result_count` and `title` --
# no edition date, because there is no edition to date. Requiring a date there
# aborted a fifty-minute live census on a root that had answered correctly.
#
# These controls are written in pairs on purpose. A refusal that fires on
# everything proves nothing, and a permit that fires on everything proves less;
# each branch below is reached by one case and denied to its neighbour.


def _ecfr(fetch, *, title_index: int = 1):
    return probe.LiveMetadataTransport(fetch)(
        "regulation_ecfr",
        {
            "cursor": None,
            "pool": sources.SOURCE_POOLS["regulation_ecfr"],
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id(
                "regulation_ecfr", title_index
            ),
        },
    )


def _page(rows, meta):
    return {"content_versions": rows, "meta": meta}


def test_an_empty_ecfr_root_is_a_declared_zero_candidate_disposition() -> None:
    """The reachable positive: title 35's exact shape must not abort the census."""
    result = _ecfr(lambda _url: _page([], {"total_pages": 1, "result_count": "0", "title": "35"}))
    assert result["items"] == []
    assert result["root_disposition"] == {
        "discovery_root_id": sources.discovery_root_id("regulation_ecfr", 1),
        "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
        "reason": "EMPTY_ENUMERATION_NO_VERSIONS",
    }


def test_a_non_empty_ecfr_root_without_an_edition_date_is_still_refused() -> None:
    """The paired negative. Emptiness is the ONLY thing that excuses a missing
    date. An enumeration that read rows but cannot say which edition they came
    from is not evidence about any edition, and the exemption above must not
    have widened into an excuse for that."""
    rows = [
        {
            "type": "section",
            "part": "1",
            "identifier": "1.1",
            "date": "2026-01-01",
            "removed": False,
        }
    ]
    with pytest.raises(protocol.SFIR3Refused, match="edition date is absent"):
        _ecfr(lambda _url: _page(rows, {"total_pages": 1, "result_count": 1, "title": "21"}))


def test_a_root_claiming_zero_while_carrying_rows_is_refused_not_called_empty() -> None:
    """Emptiness is asserted on two independent fields -- the declared count and
    the actual row list -- so a response that contradicts itself falls through to
    the refusal instead of being quietly absorbed as an empty root. This is the
    control that makes the conjunction load-bearing: with `and` weakened to `or`,
    this case would report EMPTY_ENUMERATION_NO_VERSIONS and the contradiction
    would never be seen."""
    rows = [
        {
            "type": "section",
            "part": "1",
            "identifier": "1.1",
            "date": "2026-01-01",
            "removed": False,
        }
    ]
    with pytest.raises(protocol.SFIR3Refused, match="edition date is absent"):
        _ecfr(lambda _url: _page(rows, {"total_pages": 1, "result_count": "0", "title": "21"}))


def test_a_root_claiming_rows_while_carrying_none_is_refused_not_called_empty() -> None:
    """The other half of the same conjunction, in the other direction."""
    with pytest.raises(protocol.SFIR3Refused, match="edition date is absent"):
        _ecfr(lambda _url: _page([], {"total_pages": 1, "result_count": 5, "title": "21"}))


def test_an_empty_root_carrying_a_date_still_takes_the_empty_disposition() -> None:
    """Emptiness is decided before the date is consulted, so a root that is empty
    AND dated is still a zero-candidate disposition rather than an eligible root
    with nothing in it. Without this the two branches could be reordered without
    any control noticing."""
    result = _ecfr(
        lambda _url: _page(
            [], {"total_pages": 1, "result_count": 0, "latest_amendment_date": "2026-08-19"}
        )
    )
    assert result["root_disposition"]["reason"] == "EMPTY_ENUMERATION_NO_VERSIONS"


def test_a_root_that_empties_between_the_two_censuses_is_not_called_empty() -> None:
    """Reaches the SECOND crawl's guard, which exists on a different fact. The
    first census observed rows; the second observed none. That is two censuses
    disagreeing about the corpus, and spelling it EMPTY_ENUMERATION_NO_VERSIONS
    would report a removal as a property of the root."""
    calls = 0

    def fetch(_url: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _page(
                [
                    {
                        "type": "section",
                        "part": "1",
                        "identifier": "1.1",
                        "date": "2026-01-01",
                        "removed": False,
                    }
                ],
                {"total_pages": 1, "result_count": 1, "latest_amendment_date": "2026-01-01"},
            )
        return _page([], {"total_pages": 1, "result_count": 0, "title": "21"})

    result = _ecfr(fetch)
    assert result["items"] == []
    assert result["root_disposition"]["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    assert result["root_disposition"]["reason"] == "EMPTY_ENUMERATION_DISAGREES_WITH_FIRST_CENSUS"


def test_the_three_zero_candidate_reasons_remain_distinguishable() -> None:
    """All three end at the same disposition state, and a reader who cannot tell
    them apart cannot tell "this root holds nothing" from "we could not finish
    reading this root" from "our two reads disagreed". The reasons must stay
    distinct strings."""
    source = (NS / "tools" / "probe_sfir3_capacity.py").read_text(encoding="utf-8")
    reasons = {
        "EMPTY_ENUMERATION_NO_VERSIONS",
        "EMPTY_ENUMERATION_DISAGREES_WITH_FIRST_CENSUS",
        "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
    }
    assert len(reasons) == 3
    for reason in reasons:
        assert f'"{reason}"' in source
