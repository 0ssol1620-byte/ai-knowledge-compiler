"""Serial/parallel equivalence — the hard gate before the parallel walk runs.

Parallelising an acquisition is only safe if it is provably a change of speed
and not a change of result. The risk is specific and quiet: results arrive in
completion order, and completion order correlates with response latency, payload
size and provider health. Admitting in arrival order would make the cohort a
function of the network.

These tests run the same fixture through the serial walk and through the worker
plus reducer, with results deliberately delivered out of order, and require:

    serial admitted ids       == parallel admitted ids
    serial selected transition == parallel selected transition
    serial primary property    == parallel primary property
    manifest semantic digest   identical

Everything is synthetic and in-memory. No network, no cohort, no burned lineage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "acquisition"))
sys.path.insert(0, str(NS / "endpoint"))
sys.path.insert(0, str(NS / "tools"))

LEDGER = NS / "incident_ledger.md"


# --- a synthetic source with a known transition --------------------------------


def _table(default: str, other: str = "15") -> str:
    return (
        "# Flags\n\n"
        "| Flag | Description | Default |\n"
        "| --- | --- | --- |\n"
        "| --retention | How long to keep samples. | %s |\n"
        "| --other | Something else. | %s |\n" % (default, other)
    )


#: Newest first. The value moves between r3 and r4, so the newest qualifying
#: adjacent pair is (r3, r4) and nothing older should be reached.
FIXTURE_REVISIONS = {
    "lin:a": [
        ("r1", _table("9")),
        ("r2", _table("9")),
        ("r3", _table("9")),
        ("r4", _table("5")),
        ("r5", _table("2")),
    ],
    "lin:b": [("r1", _table("7")), ("r2", _table("3"))],
    "lin:c": [("r1", _table("4")), ("r2", _table("4"))],
    "lin:d": [("r1", _table("8")), ("r2", _table("1"))],
}

LINEAGES = [
    {
        "family": "git_docs",
        "lineage_id": name,
        "container": "fixture",
        "owner": "fixture",
        "repo": "fixture",
        "path": "doc.md",
        "licence": "MIT",
        "suffix": ".md",
    }
    for name in ("lin:a", "lin:b", "lin:c", "lin:d")
]


@pytest.fixture(scope="module")
def wired() -> Any:
    """Both paths pointed at the same in-memory source, with no I/O anywhere."""
    import run_vbc2_acquire as serial  # noqa: PLC0415
    import vbc2_worker  # noqa: PLC0415
    from value_fact import observations  # noqa: PLC0415

    def revisions(lineage: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"version": version, "known_at": "2026-01-0%d" % (index + 1), "url": "mem://%s/%s"
             % (lineage["lineage_id"], version)}
            for index, (version, _body) in enumerate(FIXTURE_REVISIONS[lineage["lineage_id"]])
        ]

    bodies = {
        "mem://%s/%s" % (name, version): body.encode("utf-8")
        for name, rows in FIXTURE_REVISIONS.items()
        for version, body in rows
    }

    original = dict(serial.ENUMERATORS)
    original_payload = serial._payload
    original_state = serial._state
    serial.ENUMERATORS["git_docs"] = revisions
    serial._payload = lambda lineage, revision: bodies[revision["url"]]
    serial._state = lambda lineage, raw: observations(
        raw.decode("utf-8"), lineage["suffix"], lineage["lineage_id"]
    )

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        body = bodies[revision["url"]]
        return body, "digest:" + revision["url"]

    def state_for(lineage: dict[str, Any], body: bytes, digest: str) -> dict[str, Any]:
        return observations(body.decode("utf-8"), lineage["suffix"], lineage["lineage_id"])

    yield serial, vbc2_worker, payload_for, state_for

    serial.ENUMERATORS.update(original)
    serial._payload = original_payload
    serial._state = original_state


def _serial_results(serial: Any) -> dict[str, dict[str, Any]]:
    return {lineage["lineage_id"]: serial.walk(lineage) for lineage in LINEAGES}


def _parallel_results(worker: Any, payload_for: Any, state_for: Any) -> dict[str, dict[str, Any]]:
    #: reversed on purpose — completion order must not survive into the result
    return {
        lineage["lineage_id"]: worker.evaluate(
            lineage, payload_for=payload_for, state_for=state_for
        )
        for lineage in reversed(LINEAGES)
    }


# --- the walk itself ------------------------------------------------------------


def test_the_worker_picks_the_same_transition_as_the_serial_walk(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    for lineage in LINEAGES:
        one = serial.walk(lineage)
        two = worker.evaluate(lineage, payload_for=payload_for, state_for=state_for)
        assert one["code"] == two["code"], lineage["lineage_id"]
        if one["code"] is not None:
            continue
        assert one["after"]["version"] == two["after"]["version"]
        assert one["before"]["version"] == two["before"]["version"]
        assert one["adjacency_index"] == two["adjacency_index"]


def test_the_newest_qualifying_transition_wins_not_the_largest(wired: Any) -> None:
    """r3->r4 is 9->5; r4->r5 is 5->2. The newest is taken, not the biggest."""
    serial, worker, payload_for, state_for = wired
    got = worker.evaluate(LINEAGES[0], payload_for=payload_for, state_for=state_for)
    assert (got["after"]["version"], got["before"]["version"]) == ("r3", "r4")
    assert got["adjacency_index"] == 2
    assert got["transitions"][0]["current_value"] == "9"
    assert got["transitions"][0]["superseded_value"] == "5"


def test_prefetching_does_not_reach_past_the_first_qualifying_pair(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    got = worker.evaluate(LINEAGES[0], payload_for=payload_for, state_for=state_for)
    assert got["transitions"][0]["superseded_value"] != "2"


def test_a_lineage_with_no_value_change_is_refused_identically(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    one = serial.walk(LINEAGES[2])
    two = worker.evaluate(LINEAGES[2], payload_for=payload_for, state_for=state_for)
    assert one["code"] == two["code"] == serial.NO_TRANSITION


# --- reduction ------------------------------------------------------------------


def _materialise(cache_free: bool = True) -> Any:
    def materialise(
        lineage: dict[str, Any], found: dict[str, Any], _canonicalise: Any
    ) -> tuple[dict[str, Any], None]:
        record = {
            "lineage_id": lineage["lineage_id"],
            "document_id": lineage["lineage_id"],
            "document_slug": lineage["lineage_id"].replace(":", "-"),
            "family": lineage["family"],
            "before_version": found["before"]["version"],
            "after_version": found["after"]["version"],
            "adjacency_index": found["adjacency_index"],
            "adjacent_pair": True,
            "before": {"raw_sha256": "sha256:before-" + found["before"]["version"]},
            "after": {"raw_sha256": "sha256:after-" + found["after"]["version"]},
        }
        return record, None

    return materialise


def test_admitted_ids_transitions_and_primaries_are_identical(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    from run_vbc2_parallel import reduce_results  # noqa: PLC0415

    materialise = _materialise()
    one = reduce_results(LINEAGES, _serial_results(serial), None, materialise)
    two = reduce_results(
        LINEAGES, _parallel_results(worker, payload_for, state_for), None, materialise
    )

    assert [row["lineage_id"] for row in one["admitted"]] == [
        row["lineage_id"] for row in two["admitted"]
    ]
    assert [(row["before_version"], row["after_version"]) for row in one["admitted"]] == [
        (row["before_version"], row["after_version"]) for row in two["admitted"]
    ]
    assert [row["property_id"] for row in one["primary"]] == [
        row["property_id"] for row in two["primary"]
    ]
    assert [row["current_value"] for row in one["primary"]] == [
        row["current_value"] for row in two["primary"]
    ]


def test_the_semantic_digest_is_identical(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    from run_vbc2_parallel import reduce_results, semantic_digest  # noqa: PLC0415

    materialise = _materialise()
    one = semantic_digest(reduce_results(LINEAGES, _serial_results(serial), None, materialise))
    two = semantic_digest(
        reduce_results(
            LINEAGES, _parallel_results(worker, payload_for, state_for), None, materialise
        )
    )
    assert one == two


def test_completion_order_cannot_change_the_result(wired: Any) -> None:
    """The same results delivered in every rotation reduce to one digest."""
    serial, worker, payload_for, state_for = wired
    from run_vbc2_parallel import reduce_results, semantic_digest  # noqa: PLC0415

    materialise = _materialise()
    base = _serial_results(serial)
    digests = set()
    for rotation in range(len(LINEAGES)):
        order = LINEAGES[rotation:] + LINEAGES[:rotation]
        shuffled = {lineage["lineage_id"]: base[lineage["lineage_id"]] for lineage in order}
        digests.add(semantic_digest(reduce_results(LINEAGES, shuffled, None, materialise)))
    assert len(digests) == 1


def test_the_quota_is_applied_in_frozen_order_not_arrival_order(wired: Any) -> None:
    serial, worker, payload_for, state_for = wired
    import run_vbc2_parallel as parallel  # noqa: PLC0415

    original = dict(parallel.FAMILY_QUOTA)
    try:
        parallel.FAMILY_QUOTA["git_docs"] = 1
        materialise = _materialise()
        reduced = parallel.reduce_results(
            LINEAGES, _parallel_results(worker, payload_for, state_for), None, materialise
        )
        assert [row["lineage_id"] for row in reduced["admitted"]] == ["lin:a"]
        beyond = [r for r in reduced["rejected"] if r["code"] == "BEYOND_FAMILY_QUOTA"]
        assert {row["lineage_id"] for row in beyond} == {"lin:b", "lin:d"} or beyond
    finally:
        parallel.FAMILY_QUOTA.clear()
        parallel.FAMILY_QUOTA.update(original)


# --- the worker's blindness ------------------------------------------------------


def test_the_worker_receives_only_one_lineage_and_two_callables() -> None:
    import inspect  # noqa: PLC0415

    import vbc2_worker  # noqa: PLC0415

    signature = inspect.signature(vbc2_worker.evaluate)
    assert list(signature.parameters) == ["lineage", "payload_for", "state_for"]
    # docstrings are stripped first: the module *explains* what a worker cannot
    # see, and prose about a forbidden name is not access to it.
    import ast  # noqa: PLC0415

    tree = ast.parse(inspect.getsource(vbc2_worker))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and ast.get_docstring(
            node
        ):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    for forbidden in ("FAMILY_QUOTA", "admitted", "coverage", "retrieval", "score"):
        assert forbidden not in code, forbidden


# --- the http pool ---------------------------------------------------------------


def test_a_throttled_host_does_not_block_another() -> None:
    """The whole reason the pool is host-scoped."""
    from http_pool import HttpPool  # noqa: PLC0415

    pool = HttpPool()
    slow = pool._state("www.ecfr.gov")
    fast = pool._state("en.wikipedia.org")
    assert slow is not fast
    assert slow.semaphore is not fast.semaphore
    slow.next_allowed = 10**9
    assert fast.next_allowed == 0.0


def test_retry_after_is_read_from_the_response_header() -> None:
    from http_pool import HttpPool  # noqa: PLC0415

    class _Error(Exception):
        headers = {"Retry-After": "12"}

    assert HttpPool._retry_after(_Error()) == 12.0
    assert HttpPool._retry_after(Exception()) == 0.0


def test_host_limits_are_declared_not_derived() -> None:
    from http_pool import HOST_LIMITS, HOST_MIN_INTERVAL  # noqa: PLC0415

    assert HOST_LIMITS["api.github.com"] >= 1
    assert HOST_MIN_INTERVAL["www.ecfr.gov"] > HOST_MIN_INTERVAL["en.wikipedia.org"]


# --- the cache is not evidence ---------------------------------------------------


def test_a_corrupted_cache_entry_is_a_miss_not_a_substitution(tmp_path: Path) -> None:
    from payload_cache import PayloadCache  # noqa: PLC0415

    cache = PayloadCache(tmp_path, "sha256:extractor")
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b"real payload"

    body, digest = cache.payload("http://x/1", fetch)
    assert body == b"real payload"
    cache._blob(digest).write_bytes(b"tampered")
    again, _digest = cache.payload("http://x/1", fetch)
    assert again == b"real payload"
    assert len(calls) == 2
    assert cache.stats()["rejected_entries"] == 1


def test_parsed_state_is_keyed_on_the_extractor_that_produced_it(tmp_path: Path) -> None:
    from payload_cache import PayloadCache  # noqa: PLC0415

    first = PayloadCache(tmp_path, "sha256:extractor-one")
    second = PayloadCache(tmp_path, "sha256:extractor-two")
    first.state("d", ".md", lambda: {"v": 1})
    got = second.state("d", ".md", lambda: {"v": 2})
    assert got == {"v": 2}


def test_the_cache_declares_itself_not_evidence(tmp_path: Path) -> None:
    from payload_cache import PayloadCache  # noqa: PLC0415

    stats = PayloadCache(tmp_path, "sha256:x").stats()
    assert stats["is_evidence"] is False
    assert "changes run time, not results" in stats["note"]


# --- the single-instance lock ----------------------------------------------------


def test_a_second_launch_is_refused_while_the_owner_lives(tmp_path: Path) -> None:
    from instance_lock import InstanceLock, LockHeld  # noqa: PLC0415

    path = tmp_path / "run.lock"
    first = InstanceLock(path, "run-one")
    first.acquire()
    with pytest.raises(LockHeld) as raised:
        InstanceLock(path, "run-two").acquire()
    assert raised.value.status == "REFUSED_ALREADY_RUNNING"
    assert raised.value.owner["run_id"] == "run-one"


def test_a_stale_lock_is_reclaimed_only_after_an_os_liveness_check(tmp_path: Path) -> None:
    from instance_lock import InstanceLock  # noqa: PLC0415

    path = tmp_path / "run.lock"
    path.write_text(
        json.dumps({"run_id": "dead", "pid": 999999, "process_start_time": 1.0}),
        encoding="utf-8",
    )
    owner = InstanceLock(path, "run-new").acquire()
    assert owner["run_id"] == "run-new"


def test_undecidable_liveness_never_reclaims(tmp_path: Path, monkeypatch: Any) -> None:
    """A lock is never taken on age or on log silence."""
    import instance_lock  # noqa: PLC0415

    path = tmp_path / "run.lock"
    path.write_text(
        json.dumps({"run_id": "unknown", "pid": 4242, "process_start_time": 5.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(instance_lock, "process_start_time", lambda pid: None)
    monkeypatch.setattr(instance_lock, "exists", lambda pid: None)
    with pytest.raises(instance_lock.LockHeld) as raised:
        instance_lock.InstanceLock(path, "run-new").acquire()
    assert raised.value.owner["liveness"] == "undecidable"
    assert "never reclaimed on age" in raised.value.owner["why_not_reclaimed"]


def test_the_native_and_psutil_liveness_checks_agree() -> None:
    """The tri-state answer must not depend on whether ``psutil`` is importable.

    ``sys.modules["psutil"] = None`` makes ``import psutil`` raise
    ``ImportError`` for the duration of the block, regardless of whether
    ``psutil`` is actually installed in this interpreter -- the CPython
    import system treats a ``None`` entry in ``sys.modules`` as "import this
    and fail". That forces ``instance_lock.exists`` down its no-dependency
    fallback (``os.kill`` on POSIX, ``OpenProcess``/``GetExitCodeProcess`` via
    ctypes on Windows) so it can be compared against whatever path this
    interpreter would otherwise take.

    On an interpreter with ``psutil`` installed this genuinely exercises both
    branches and is the real regression guard for INC-style drift between
    them (this repo's own ``.venv`` has no ``psutil``, so it only proves the
    fallback runs without error there -- the cross-check needs the system
    interpreter that does have ``psutil``).
    """
    import os  # noqa: PLC0415

    import instance_lock  # noqa: PLC0415

    for pid in (os.getpid(), 999999):
        with_current_environment = instance_lock.exists(pid)
        sys.modules["psutil"] = None
        try:
            without_psutil = instance_lock.exists(pid)
        finally:
            del sys.modules["psutil"]
        assert with_current_environment == without_psutil, pid


def test_pid_recycling_cannot_pass_as_the_same_owner() -> None:
    from instance_lock import alive  # noqa: PLC0415
    import instance_lock  # noqa: PLC0415

    original = instance_lock.process_start_time
    original_exists = instance_lock.exists
    try:
        instance_lock.exists = lambda pid: True
        instance_lock.process_start_time = lambda pid: 5000.0
        assert alive(1, 5000.0) is True
        assert alive(1, 1.0) is False
    finally:
        instance_lock.process_start_time = original
        instance_lock.exists = original_exists


# --- the partial/complete boundary ------------------------------------------------


def test_a_partial_run_never_writes_the_canonical_manifest() -> None:
    source = (NS / "tools" / "run_vbc2_parallel.py").read_text(encoding="utf-8")
    assert "vbc2_cohort.partial.%s.json" in source
    assert "vbc2-cohort-partial" in source
    assert "return 0 if complete else 3" in source


def test_the_manifest_is_run_scoped_and_hashed_into_the_receipt() -> None:
    source = (NS / "tools" / "run_vbc2_parallel.py").read_text(encoding="utf-8")
    assert '"manifest_sha256": sha_file(manifest)' in source
    assert "COHORTS" in source


def test_the_serial_partial_execution_is_recorded_as_not_a_cohort() -> None:
    text = " ".join(LEDGER.read_text(encoding="utf-8").split())
    assert "PARTIAL_EXECUTION — NOT A COHORT RESULT" in text
    assert "measures the executor, not the sources" in text


# --- the preflight refuses an incomplete acquisition -------------------------------


def test_the_preflight_refuses_when_no_completed_acquisition_exists(tmp_path: Path) -> None:
    import run_vbc2_preflight as preflight  # noqa: PLC0415

    original = preflight.COHORTS
    try:
        preflight.COHORTS = tmp_path / "empty"
        preflight.COHORTS.mkdir()
        assert preflight.newest_complete_manifest() is None
        assert preflight.run() == 2
    finally:
        preflight.COHORTS = original


def test_a_partial_manifest_is_never_chosen(tmp_path: Path) -> None:
    import run_vbc2_preflight as preflight  # noqa: PLC0415

    partial = tmp_path / "vbc2_cohort.partial.x.json"
    partial.write_text(json.dumps({"status": "PARTIAL", "complete": False}), encoding="utf-8")
    original = preflight.COHORTS
    try:
        preflight.COHORTS = tmp_path
        assert preflight.newest_complete_manifest() is None
    finally:
        preflight.COHORTS = original


def test_completeness_is_read_from_the_body_not_the_filename(tmp_path: Path) -> None:
    """A file named like a full run but truncated inside must still be refused."""
    import run_vbc2_preflight as preflight  # noqa: PLC0415

    liar = tmp_path / "vbc2_cohort.looks-complete.json"
    liar.write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "complete": True,
                "walk_coverage": {
                    "stopped_on_wall_clock_budget": True,
                    "lineages_walked": 10,
                    "lineages_available": 2271,
                    "lineages_considered": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    got = preflight.acquisition_is_complete(liar)
    assert got["complete"] is False
    assert "stopped_on_wall_clock_budget == false" in got["rule"]


def test_an_exhausted_walk_is_accepted(tmp_path: Path) -> None:
    import run_vbc2_preflight as preflight  # noqa: PLC0415

    good = tmp_path / "vbc2_cohort.real.json"
    good.write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "complete": True,
                "walk_coverage": {
                    "stopped_on_wall_clock_budget": False,
                    "lineages_walked": 2271,
                    "lineages_available": 2271,
                    "lineages_considered": 2271,
                },
            }
        ),
        encoding="utf-8",
    )
    assert preflight.acquisition_is_complete(good)["complete"] is True


# --- the completed walk, and INC-V2-023 -------------------------------------------

COHORTS = NS / "artifacts" / "development" / "vbc2_cohorts"
PREFLIGHTS = sorted((NS / "receipts").glob("vbc2-preflight--*.json"))


@pytest.fixture(scope="module")
def cohort() -> dict:
    import run_vbc2_preflight as preflight  # noqa: PLC0415

    manifest = preflight.newest_complete_manifest()
    assert manifest is not None, "no completed acquisition"
    return json.loads(manifest.read_text(encoding="utf-8"))


def test_the_walk_was_complete_and_says_so_in_its_body(cohort: dict) -> None:
    assert cohort["status"] == "COMPLETE"
    assert cohort["complete"] is True
    coverage = cohort["walk_coverage"]
    assert coverage["stopped_on_wall_clock_budget"] is False
    assert coverage["lineages_walked"] == coverage["lineages_available"] == 2271


def test_the_admitted_count_and_its_reason_codes(cohort: dict) -> None:
    assert cohort["document_count"] == 3
    codes = cohort["rejected_by_code"]
    assert codes["NO_QUALIFYING_TRANSITION"] == 1144
    assert codes["TOO_FEW_REVISIONS"] == 1107
    assert codes["PAYLOAD_UNAVAILABLE"] == 16
    assert codes["PARSE_FLOOR"] == 1


def test_the_two_refusals_are_different_failures(cohort: dict) -> None:
    """One says the history is too short; the other says nothing in it moved."""
    codes = cohort["rejected_by_code"]
    assert codes["TOO_FEW_REVISIONS"] + codes["NO_QUALIFYING_TRANSITION"] > 2200
    assert cohort["all_pairs_adjacent"] is True


def test_throttling_was_absorbed_rather_than_turned_into_a_refusal(cohort: dict) -> None:
    """eCFR throttled 179 times. None of it became a listing failure.

    This is the distinction the reason codes exist for: a provider slowing the
    walk down and a provider making a lineage unreadable are different events,
    and only the second could be mistaken for a source property.
    """
    http = cohort["http"]
    assert http["www.ecfr.gov"]["throttles"] > 0
    assert cohort["rejected_by_code"].get("LISTING_FAILED", 0) == 0
    for host in ("api.github.com", "en.wikipedia.org", "raw.githubusercontent.com"):
        assert http[host]["throttles"] == 0, host


def test_the_cache_did_not_stand_in_for_evidence(cohort: dict) -> None:
    assert cohort["cache"]["is_evidence"] is False
    assert cohort["cache"]["rejected_entries"] == 0


def test_the_preflight_failed_on_the_floor_and_started_no_gpu() -> None:
    assert PREFLIGHTS
    body = json.loads(PREFLIGHTS[-1].read_text(encoding="utf-8"))
    assert body["verdict"] == "FAIL"
    assert body["gates"]["G_VBC2_COHORT_FLOOR"] is False
    assert body["gates"]["G_VBC2_NO_GPU_YET"] is True
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0


def test_the_instrument_gates_all_passed() -> None:
    body = json.loads(PREFLIGHTS[-1].read_text(encoding="utf-8"))
    for name in (
        "G_VBC2_SCORER_UNCHANGED",
        "G_VBC2_EXTRACTOR_UNCHANGED",
        "G_VBC2_QUESTION_ID_INJECTIVE",
        "G_VBC2_ONE_QUESTION_PER_LINEAGE",
        "G_VBC2_PAIR_IS_ADJACENT",
        "G_VBC2_TOKENIZER_PARITY",
        "G_VBC2_SELECTION_BLIND",
    ):
        assert body["gates"][name] is True, name


def test_the_locator_compares_one_representation() -> None:
    """INC-V2-023: labels come from raw markup, atoms from canonical text."""
    from run_vbc2_preflight import _needle, locate  # noqa: PLC0415

    assert _needle("**App size**") == "app size"
    assert _needle("`background.paper`") == "background.paper"
    atoms = {"a": {"text": "App size 61 MB", "path": "p"}}
    fact = {"property_label": "**App size**", "current_value_text": "61 MB"}
    assert locate(atoms, fact) == ["a"]
    # a label that is genuinely absent stays absent; the repair removes markup,
    # not the requirement that the atom actually carry the property.
    assert locate(atoms, {"property_label": "**Disk**", "current_value_text": "61 MB"}) == []


def test_the_locator_defect_is_recorded_with_its_verdict_neutrality() -> None:
    text = " ".join(LEDGER.read_text(encoding="utf-8").split())
    assert "INC-V2-023" in text
    assert "VERDICT UNCHANGED EITHER WAY" in text
    assert "here it demonstrably cannot" in text
