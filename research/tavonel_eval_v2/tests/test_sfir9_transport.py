"""Controls for the SFIR9 transport contract.

Every test that concerns behaviour drives the real frozen SFIR8 implementation
through a scripted opener rather than a hand-built stub. INC-V2-113 has recurred
six times in this study: a unit test of a guard is not a test that the guard is
wired in, and a wrapper is exactly the place where a guard gets declared and then
not reached.

The equivalence section is the one that needs stating carefully. Comparing the
wrapper against the implementation it delegates to could be vacuous -- delegation
makes agreement true by construction. What makes it informative is the other
half: on the inputs SFIR9 forbids, the two must *disagree*, with SFIR8 proceeding
and SFIR9 refusing. Agreement alone would prove nothing; agreement plus
discrimination is what shows the narrowing is exactly where it was declared.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_transport as upstream_transport  # noqa: E402
import sfir9_protocol as protocol  # noqa: E402
import sfir9_transport as sfir9  # noqa: E402

# ---------------------------------------------------------------- stub server


class _Headers(dict):
    def get(self, name, default=None):
        for key, value in self.items():
            if key.casefold() == name.casefold():
                return value
        return default


class _Response(io.BytesIO):
    def __init__(self, status, headers, body):
        super().__init__(body)
        self.status = status
        self.headers = _Headers(headers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Server:
    def __init__(self, routes):
        self.routes = routes
        self.seen: list[str] = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.seen.append(url)
        if url not in self.routes:
            raise AssertionError(f"unscripted request to {url}")
        status, headers, body = self.routes[url]
        return _Response(status, headers, body)


def _install(monkeypatch, routes):
    server = _Server(routes)
    monkeypatch.setattr(
        upstream_transport.urllib.request, "build_opener", lambda *a: server
    )
    return server


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _rate(remaining, request_id="req-1"):
    return {"x-ratelimit-remaining": str(remaining), "x-github-request-id": request_id}


def _client(**overrides):
    body = dict(
        upstream=upstream_transport.ManualRedirectTransport(),
        roster_digest="sha256:roster",
        selection_digest="sha256:selection",
    )
    body.update(overrides)
    client = sfir9.Sfir9Transport(**body)
    client._upstream.seed_remaining(5000)
    return client


REPO_URL = "https://api.github.com/repos/old-org/old-name"
NEW_URL = "https://api.github.com/repos/new-org/new-name"


def _renamed_routes():
    """A catalogue address that redirects to the same numeric repository."""
    return {
        REPO_URL: (301, {"Location": NEW_URL, **_rate(4999, "req-a")}, b""),
        NEW_URL: (
            200,
            _rate(4998, "req-b"),
            _json({"id": 12345, "full_name": "new-org/new-name", "default_branch": "main"}),
        ),
    }


# ------------------------------------------------------------ declared surface


def test_the_surface_declares_one_scheme_one_host_one_method():
    surface = sfir9.declared_surface()
    assert surface["allowed_scheme"] == "https"
    assert surface["allowed_host"] == "api.github.com"
    assert surface["allowed_method"] == "GET"


def test_the_surface_declares_every_behaviour_the_ruling_names():
    surface = sfir9.declared_surface()
    for key in (
        "redirect_policy",
        "canonical_address_adoption_rule",
        "numeric_repository_id_attestation_rule",
        "accounting",
        "rate_window",
        "segment_close_condition",
        "checkpoint_handoff",
    ):
        assert key in surface, f"{key} is not declared, so it is not permitted"


def test_the_surface_is_a_contract_that_can_be_hashed():
    assert sfir9.surface_digest().startswith("sha256:")
    assert sfir9.surface_digest() == sfir9.surface_digest()


def test_the_surface_binds_the_protocol_digest():
    """A surface that did not name its protocol could outlive it."""
    assert sfir9.declared_surface()["protocol_digest"] == protocol.Protocol().digest()


def test_the_fail_safes_are_not_duplicated_as_literals():
    """`sfir9_protocol` is the authority; a second copy is a second authority.

    A duplicate literal can be raised on its own when a run is going badly, and
    nothing that reads the protocol would notice.
    """
    source = (NS / "tools/sfir9_transport.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if "protocol.RETRY_WAIT" not in line
    )
    assert "= 60" not in body
    assert "= 180" not in body
    window = sfir9.declared_surface()["rate_window"]
    assert window["retry_wait_fail_safe_seconds"] == protocol.RETRY_WAIT_SECONDS
    assert window["cumulative_wait_fail_safe_seconds"] == protocol.TOTAL_WAIT_SECONDS


def test_the_surface_moves_when_the_protocol_moves(monkeypatch):
    baseline = sfir9.surface_digest()
    monkeypatch.setattr(protocol, "RETRY_WAIT_SECONDS", 45)
    assert sfir9.surface_digest() != baseline


@pytest.mark.parametrize(
    "constant,key",
    [
        ("RETRY_WAIT_SECONDS", "retry_wait_fail_safe_seconds"),
        ("TOTAL_WAIT_SECONDS", "cumulative_wait_fail_safe_seconds"),
    ],
)
def test_the_surface_reads_each_fail_safe_rather_than_copying_it(
    monkeypatch, constant, key
):
    """Equal values do not establish that one is derived from the other.

    A literal that happens to match the protocol passes any equality check
    written against today's numbers, and then stays behind when the protocol
    moves. Moving the protocol is the only thing that tells them apart.
    """
    monkeypatch.setattr(protocol, constant, 7)
    assert sfir9.declared_surface()["rate_window"][key] == 7


# ------------------------------------------------------- upstream byte binding


def test_the_manifest_pins_the_six_upstream_modules():
    assert {m.module for m in sfir9.UPSTREAM_MODULES} == {
        "sfir8_transport",
        "sfir8_traversal",
        "sfir8_frontier",
        "sfir8_checkpoint",
        "sfir8_hop_accounting",
        "sfir8_provider_accounting",
    }


def test_every_pinned_module_carries_all_four_bindings():
    for pinned in sfir9.UPSTREAM_MODULES:
        assert pinned.relative_path.endswith(f"{pinned.module}.py")
        assert pinned.sha256.startswith("sha256:")
        assert len(pinned.git_blob_id) == 40


def test_the_git_blob_id_is_computed_the_way_git_computes_it():
    """Recomputed here so the pin is checkable without a repository."""
    assert sfir9.git_blob_id_of(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert (
        sfir9.git_blob_id_of(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    )


def test_the_real_upstream_binding_passes_against_this_repository():
    """The completion condition, run against the actual commit and working tree."""
    result = sfir9.verify_upstream_binding(
        repository_root=REPO, import_origins=sfir9.import_origins()
    )
    assert len(result["upstream_modules"]) == 6
    for record in result["upstream_modules"]:
        assert record["committed_bytes_equal_working_bytes"] is True
        assert record["import_origin_inside_frozen_checkout"] is True


def _fake_tree(tmp_path, mutate=None):
    """A checkout holding the real upstream bytes, optionally perturbed."""
    tools = tmp_path / "research/tavonel_eval_v2/tools"
    tools.mkdir(parents=True)
    committed: dict[str, bytes] = {}
    origins: dict[str, str] = {}
    for pinned in sfir9.UPSTREAM_MODULES:
        raw = (REPO / pinned.relative_path).read_bytes()
        committed[pinned.relative_path] = raw
        written = mutate(pinned, raw) if mutate else raw
        (tmp_path / pinned.relative_path).write_bytes(written)
        origins[pinned.module] = str(tools / f"{pinned.module}.py")
    return committed, origins


def _repinned(module, *, sha256=None, git_blob_id=None):
    """The manifest with one module's pins replaced."""
    return tuple(
        sfir9.UpstreamModule(
            module=m.module,
            relative_path=m.relative_path,
            sha256=sha256 if (m.module == module and sha256) else m.sha256,
            git_blob_id=(
                git_blob_id if (m.module == module and git_blob_id) else m.git_blob_id
            ),
        )
        for m in sfir9.UPSTREAM_MODULES
    )


def _verify_with_manifest(manifest, tmp_path, committed, origins):
    original = sfir9.UPSTREAM_MODULES
    sfir9.UPSTREAM_MODULES = manifest
    try:
        return sfir9.verify_upstream_binding(
            repository_root=tmp_path,
            import_origins=origins,
            read_committed_bytes=lambda _root, path: committed[path],
        )
    finally:
        sfir9.UPSTREAM_MODULES = original


def test_the_content_hash_pin_is_checked_on_its_own(tmp_path):
    """Both pins are functions of the same bytes, so editing a file trips both.

    Only a manifest whose two pins disagree with each other can tell which of the
    two comparisons is doing the work -- and a manifest is exactly what an editor
    touches when re-pinning after a change.
    """
    committed, origins = _fake_tree(tmp_path)
    manifest = _repinned("sfir8_frontier", sha256="sha256:" + "0" * 64)
    with pytest.raises(sfir9.TransportRefused) as caught:
        _verify_with_manifest(manifest, tmp_path, committed, origins)
    assert caught.value.code == sfir9.UPSTREAM_HASH
    assert "hashes to" in str(caught.value)


def test_the_git_blob_pin_is_checked_on_its_own(tmp_path):
    committed, origins = _fake_tree(tmp_path)
    manifest = _repinned("sfir8_frontier", git_blob_id="0" * 40)
    with pytest.raises(sfir9.TransportRefused) as caught:
        _verify_with_manifest(manifest, tmp_path, committed, origins)
    assert caught.value.code == sfir9.UPSTREAM_HASH
    assert "Git blob id" in str(caught.value)


def test_a_changed_upstream_hash_refuses(tmp_path):
    def mutate(pinned, raw):
        return raw + b"\n# one added comment\n" if pinned.module == "sfir8_frontier" else raw

    committed, origins = _fake_tree(tmp_path, mutate)
    with pytest.raises(sfir9.TransportRefused) as caught:
        sfir9.verify_upstream_binding(
            repository_root=tmp_path,
            import_origins=origins,
            read_committed_bytes=lambda _root, path: committed[path],
        )
    assert caught.value.code == sfir9.UPSTREAM_HASH


def test_working_bytes_differing_from_the_committed_blob_refuses(tmp_path):
    """The bytes hash correctly against a manifest that was also updated.

    This is the substitution the hash pin alone cannot catch: someone edits the
    implementation and re-pins the manifest to match, leaving the commit behind.
    """
    committed, origins = _fake_tree(tmp_path)
    # Same length, different bytes: a comparison on size alone would not see it.
    original_bytes = committed["research/tavonel_eval_v2/tools/sfir8_frontier.py"]
    changed = original_bytes.replace(b"frontier", b"frontieR", 1)
    assert len(changed) == len(original_bytes) and changed != original_bytes
    (tmp_path / "research/tavonel_eval_v2/tools/sfir8_frontier.py").write_bytes(changed)

    manifest = tuple(
        sfir9.UpstreamModule(
            module=m.module,
            relative_path=m.relative_path,
            sha256=sfir9.sha256_of(changed) if m.module == "sfir8_frontier" else m.sha256,
            git_blob_id=(
                sfir9.git_blob_id_of(changed)
                if m.module == "sfir8_frontier"
                else m.git_blob_id
            ),
        )
        for m in sfir9.UPSTREAM_MODULES
    )
    original = sfir9.UPSTREAM_MODULES
    sfir9.UPSTREAM_MODULES = manifest
    try:
        with pytest.raises(sfir9.TransportRefused) as caught:
            sfir9.verify_upstream_binding(
                repository_root=tmp_path,
                import_origins=origins,
                read_committed_bytes=lambda _root, path: committed[path],
            )
    finally:
        sfir9.UPSTREAM_MODULES = original
    assert caught.value.code == sfir9.UPSTREAM_BYTES


def test_an_import_from_a_shared_tree_refuses_even_though_every_hash_agrees(tmp_path):
    """Hash equality is not origin equality -- the `.pth` failure, mechanically."""
    committed, origins = _fake_tree(tmp_path)
    origins["sfir8_traversal"] = "/some/other/worktree/tools/sfir8_traversal.py"
    with pytest.raises(sfir9.TransportRefused) as caught:
        sfir9.verify_upstream_binding(
            repository_root=tmp_path,
            import_origins=origins,
            read_committed_bytes=lambda _root, path: committed[path],
        )
    assert caught.value.code == sfir9.IMPORT_ORIGIN
    assert "hash correctly" in str(caught.value)


def test_an_unimported_module_is_not_a_passing_module(tmp_path):
    committed, origins = _fake_tree(tmp_path)
    del origins["sfir8_checkpoint"]
    with pytest.raises(sfir9.TransportRefused) as caught:
        sfir9.verify_upstream_binding(
            repository_root=tmp_path,
            import_origins=origins,
            read_committed_bytes=lambda _root, path: committed[path],
        )
    assert caught.value.code == sfir9.IMPORT_ORIGIN


def test_a_clean_tree_passes_the_same_check(tmp_path):
    """The refusals must be about the defect, not about being checked at all."""
    committed, origins = _fake_tree(tmp_path)
    result = sfir9.verify_upstream_binding(
        repository_root=tmp_path,
        import_origins=origins,
        read_committed_bytes=lambda _root, path: committed[path],
    )
    assert len(result["upstream_modules"]) == 6


def test_the_binding_says_what_is_reused_and_what_is_not():
    result = sfir9.verify_upstream_binding(
        repository_root=REPO, import_origins=sfir9.import_origins()
    )
    reused = result["what_is_reused"]
    assert "implementation bytes" in reused
    assert "no sfir8 receipt is a prerequisite" in reused.lower()


def test_import_origins_reads_what_python_did_not_what_we_intended():
    origins = sfir9.import_origins()
    assert set(origins) == {m.module for m in sfir9.UPSTREAM_MODULES}
    assert origins["sfir8_transport"] == upstream_transport.__file__


# --------------------------------------------------------------- target gating


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/a/b",
        "https://api.github.com.evil.test/repos/a/b",
        "https://evil-api.github.com/repos/a/b",
        "https://notapi.github.com/repos/a/b",
        "https://raw.githubusercontent.com/a/b",
        "ftp://api.github.com/repos/a/b",
    ],
)
def test_a_target_outside_the_permitted_surface_refuses(url):
    with pytest.raises(sfir9.TransportRefused) as caught:
        sfir9.require_permitted_target(url)
    assert caught.value.code == sfir9.DISALLOWED_TARGET


def test_the_permitted_target_passes():
    sfir9.require_permitted_target("https://api.github.com/repos/a/b")


def test_the_client_refuses_a_disallowed_target_before_opening_a_socket(monkeypatch):
    server = _install(monkeypatch, {})
    client = _client()
    with pytest.raises(sfir9.TransportRefused):
        client.get("https://example.test/repos/a/b")
    assert server.seen == []


# --------------------------------------------------------- explicit redirects


def test_a_redirect_is_followed_by_the_instrument_one_hop_at_a_time(monkeypatch):
    """If the library followed it, only one response would ever be seen.

    This is the discriminating control for automatic following: the count of
    recorded hops is two precisely because the instrument issued both requests.
    """
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    assert len(client.hops) == 2
    assert [hop.hop_index for hop in client.hops] == [0, 1]
    assert client.hops[0].status == 301
    assert client.hops[1].status == 200


def test_the_installed_handler_does_not_follow_redirects():
    assert upstream_transport.ManualRedirectTransport().follows_redirects_automatically() is False
    assert sfir9.declared_surface()["redirect_policy"]["automatic_following"] is False


def test_every_hop_carries_the_fields_the_ruling_names(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    for atom in client.receipt()["hops"]:
        for key in (
            "logical_request_id",
            "hop_index",
            "requested_url",
            "status",
            "redirect_location_digest",
            "response_body_sha256",
            "provider_remaining",
            "provider_reset_epoch",
            "provider_request_id",
        ):
            assert key in atom


def test_the_redirect_target_is_recorded_as_a_digest_not_a_url(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert client.hops[0].redirect_location_digest.startswith("sha256:")
    assert client.hops[1].redirect_location_digest is None


def test_hops_belonging_to_one_logical_request_share_its_id(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert len({hop.logical_request_id for hop in client.hops}) == 1


def test_a_redirect_without_a_location_is_refused_by_the_frozen_upstream(monkeypatch):
    """The refusal lives upstream, so it is tested upstream rather than mirrored.

    A second check in the wrapper could never fire -- the upstream raises before
    returning a record -- and a guard placed where its failure is impossible is
    not a guard (INC-V2-036). What the wrapper owes is that the behaviour exists
    on the path it actually uses, which is what this drives.
    """
    _install(monkeypatch, {REPO_URL: (301, _rate(4999), b"")})
    client = _client()
    with pytest.raises(upstream_transport.RedirectRefused):
        client.get(REPO_URL)
    assert sfir9.declared_surface()["redirect_policy"][
        "a_redirect_without_a_location_is_refused"
    ] == sfir9.REDIRECT_UNRESOLVED


def test_a_redirect_leaving_the_permitted_host_is_not_followed(monkeypatch):
    _install(
        monkeypatch,
        {
            REPO_URL: (
                301,
                {"Location": "https://evil.test/repos/x/y", **_rate(4999)},
                b"",
            ),
            "https://evil.test/repos/x/y": (200, _rate(4998), _json({"id": 12345})),
        },
    )
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.get(REPO_URL)
    assert caught.value.code == sfir9.DISALLOWED_TARGET


# ------------------------------------------------------------------- identity


def test_the_canonical_address_is_adopted_only_after_the_id_matches(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    identity = client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    assert identity.verified is True
    assert identity.observed_numeric_id == "12345"
    assert identity.canonical_address == "new-org/new-name"
    assert client.address_for("old-org/old-name") == "new-org/new-name"


def test_a_different_numeric_id_refuses_and_adopts_nothing(monkeypatch):
    _install(
        monkeypatch,
        {
            REPO_URL: (301, {"Location": NEW_URL, **_rate(4999)}, b""),
            NEW_URL: (
                200,
                _rate(4998),
                _json({"id": 99999, "full_name": "someone-else/repo"}),
            ),
        },
    )
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert caught.value.code == sfir9.IDENTITY_MISMATCH
    assert client.roots == {}


def test_no_address_may_be_used_before_the_identity_is_proved():
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.address_for("old-org/old-name")
    assert caught.value.code == sfir9.UNPROVEN_IDENTITY


def test_an_unverified_identity_in_the_root_table_is_still_refused():
    """`roots` is public, so "it only ever holds verified entries" is a habit.

    The guard has two halves -- absent, and present but unproved -- and only the
    first is reachable through the class's own methods. This reaches the second.
    """
    client = _client()
    client.roots["old-org/old-name"] = sfir9.RootIdentity(
        catalogue_address="old-org/old-name",
        host_uuid="12345",
        canonical_address="new-org/new-name",
        verified=False,
    )
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.address_for("old-org/old-name")
    assert caught.value.code == sfir9.UNPROVEN_IDENTITY


def test_an_unproved_identity_falls_back_to_the_catalogue_address():
    unproved = sfir9.RootIdentity(
        catalogue_address="old-org/old-name",
        host_uuid="12345",
        canonical_address="new-org/new-name",
        verified=False,
    )
    assert unproved.address_to_use() == "old-org/old-name"


def test_metadata_that_does_not_answer_200_refuses(monkeypatch):
    """The body carries the right id, so only the status check can refuse it.

    An error page that happens to contain a matching id is not an attestation.
    With a body of `{}` this control would pass even without the status check,
    because the missing id would refuse it instead -- the guard would look tested
    while never being reached.
    """
    _install(
        monkeypatch,
        {
            REPO_URL: (
                404,
                _rate(4999),
                _json({"id": 12345, "full_name": "old-org/old-name"}),
            )
        },
    )
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert caught.value.code == sfir9.IDENTITY_MISMATCH
    assert "HTTP 404" in str(caught.value)


def test_a_response_without_a_usable_canonical_name_refuses(monkeypatch):
    _install(monkeypatch, {REPO_URL: (200, _rate(4999), _json({"id": 12345}))})
    client = _client()
    with pytest.raises(sfir9.TransportRefused):
        client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")


def test_the_unrenamed_case_adopts_the_same_address(monkeypatch):
    _install(
        monkeypatch,
        {
            REPO_URL: (
                200,
                _rate(4999),
                _json({"id": 12345, "full_name": "old-org/old-name"}),
            )
        },
    )
    client = _client()
    identity = client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert identity.as_dict()["renamed"] is False
    assert len(client.hops) == 1


# ------------------------------------------------------------ three counters


def test_the_three_counters_are_reported_separately_and_differ(monkeypatch):
    """One logical request, two hops, two charges. Three distinct quantities."""
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    counters = client.counters()
    assert counters.logical_requests == 1
    assert counters.network_hops == 2
    assert counters.provider_charged_requests == 2
    assert counters.logical_requests != counters.network_hops


def test_the_counters_are_named_fields_not_a_summable_collection():
    counters = sfir9.Counters(
        logical_requests=1, network_hops=2, provider_charged_requests=3
    )
    assert not isinstance(counters, (list, tuple, dict))
    reported = counters.as_dict()
    assert reported["logical_requests"] == 1
    assert reported["network_hops"] == 2
    assert reported["provider_charged_requests"] == 3
    assert "790" in reported["why_they_are_kept_apart"]


def test_no_hop_is_omitted_from_the_accounting(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert client.counters().network_hops == len(client.receipt()["hops"])
    assert client.counters().network_hops == sum(
        entry["network_hops"] for entry in client.logical_requests
    )


def test_equal_counters_on_one_run_do_not_make_them_one_quantity(monkeypatch):
    """The unrenamed case gives 1/1/1. The names must still be three."""
    _install(
        monkeypatch,
        {
            REPO_URL: (
                200,
                _rate(4999),
                _json({"id": 12345, "full_name": "old-org/old-name"}),
            )
        },
    )
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    reported = client.counters().as_dict()
    assert reported["logical_requests"] == reported["network_hops"] == 1
    named = {"logical_requests", "network_hops", "provider_charged_requests"}
    assert named <= set(reported), (
        "the counters reported one number under three names on this run, but the "
        "three names must survive the coincidence"
    )


def test_the_charge_count_is_read_from_the_provider_not_from_the_hop_count(monkeypatch):
    """Two hops charged three. SFIR8 observed exactly this asymmetry.

    Every other fixture here happens to charge one per hop, which makes the two
    counters numerically equal and so interchangeable to a test. This separates
    them.
    """
    _install(
        monkeypatch,
        {
            REPO_URL: (301, {"Location": NEW_URL, **_rate(4999, "req-a")}, b""),
            NEW_URL: (
                200,
                _rate(4997, "req-b"),
                _json({"id": 12345, "full_name": "new-org/new-name"}),
            ),
        },
    )
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    counters = client.counters()
    assert counters.network_hops == 2
    assert counters.provider_charged_requests == 3


# ------------------------------------------------------- provider accounting


def test_a_matching_provider_delta_is_reported_as_complete(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    result = client.reconcile_provider(window_used_delta=2)
    assert result[sfir9.UNATTRIBUTED] == 0
    assert result["accounting_is_complete"] is True


def test_a_difference_is_recorded_and_not_attributed(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    result = client.reconcile_provider(window_used_delta=5)
    assert result[sfir9.UNATTRIBUTED] == 3
    assert result["accounting_is_complete"] is False
    assert "identical arithmetic" in result["what_a_nonzero_delta_does_not_establish"]


def test_the_sfir8_zero_delta_is_not_carried_forward_as_a_guarantee(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    result = client.reconcile_provider(window_used_delta=None)
    assert result[sfir9.UNATTRIBUTED] is None
    assert "guarantees nothing about this one" in result["sfir8_observation_is_not_a_guarantee"]


# ------------------------------------------------------------- the rate window


def test_a_window_with_requests_remaining_continues():
    decision = sfir9.plan_wait(
        remaining=100, reset_epoch=None, retry_after=None, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.CONTINUE


def test_a_short_wait_inside_the_fail_safe_is_taken():
    decision = sfir9.plan_wait(
        remaining=0, reset_epoch=30, retry_after=None, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.WAIT
    assert decision.seconds == 30


def test_a_wait_past_the_per_retry_fail_safe_closes_the_segment():
    decision = sfir9.plan_wait(
        remaining=0,
        reset_epoch=protocol.RETRY_WAIT_SECONDS + 1,
        retry_after=None,
        now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.SEGMENT_CLOSE_RATE_WINDOW


def test_the_boundary_second_is_still_inside_the_fail_safe():
    decision = sfir9.plan_wait(
        remaining=0,
        reset_epoch=protocol.RETRY_WAIT_SECONDS,
        retry_after=None,
        now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.WAIT
    assert decision.seconds == protocol.RETRY_WAIT_SECONDS


def test_a_wait_past_the_cumulative_fail_safe_closes_the_segment():
    decision = sfir9.plan_wait(
        remaining=0,
        reset_epoch=40,
        retry_after=None,
        now_epoch=0,
        cumulative_waited_seconds=protocol.TOTAL_WAIT_SECONDS - 39,
    )
    assert decision.action == sfir9.SEGMENT_CLOSE_RATE_WINDOW
    assert "cumulative fail-safe" in decision.reason


def test_retry_after_is_honoured_and_still_bounded():
    inside = sfir9.plan_wait(
        remaining=0, reset_epoch=None, retry_after=10, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert inside.action == sfir9.WAIT and inside.seconds == 10

    outside = sfir9.plan_wait(
        remaining=0, reset_epoch=None, retry_after=3600, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert outside.action == sfir9.SEGMENT_CLOSE_RATE_WINDOW


def test_retry_after_applies_even_when_requests_appear_to_remain():
    """The provider asking us to stop outranks our reading of the counter."""
    decision = sfir9.plan_wait(
        remaining=500, reset_epoch=None, retry_after=5, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.WAIT


def test_an_exhausted_window_with_no_reset_time_closes_rather_than_guessing():
    decision = sfir9.plan_wait(
        remaining=0, reset_epoch=None, retry_after=None, now_epoch=0,
        cumulative_waited_seconds=0,
    )
    assert decision.action == sfir9.SEGMENT_CLOSE_RATE_WINDOW
    assert "must not be guessed" in decision.reason


def test_no_wait_ever_exceeds_the_per_retry_fail_safe():
    for reset in range(0, 400, 7):
        decision = sfir9.plan_wait(
            remaining=0, reset_epoch=reset, retry_after=None, now_epoch=0,
            cumulative_waited_seconds=0,
        )
        assert decision.seconds <= protocol.RETRY_WAIT_SECONDS


def test_cumulative_waiting_never_exceeds_the_total_fail_safe():
    client = _client(clock=lambda: 0)
    for _ in range(20):
        client.observe_rate_window(remaining=0, reset_epoch=50, retry_after=None)
        if client.segment_closed:
            break
    assert client.cumulative_waited_seconds <= protocol.TOTAL_WAIT_SECONDS
    assert client.segment_closed == sfir9.SEGMENT_CLOSE_RATE_WINDOW


def test_a_closed_segment_issues_no_further_request(monkeypatch):
    """The polling loop, refused. The window state is already known."""
    server = _install(monkeypatch, _renamed_routes())
    client = _client()
    client.observe_rate_window(remaining=0, reset_epoch=100_000, retry_after=None)
    assert client.segment_closed == sfir9.SEGMENT_CLOSE_RATE_WINDOW

    with pytest.raises(sfir9.TransportRefused) as caught:
        client.get(REPO_URL)
    assert "polling loop" in str(caught.value)
    assert server.seen == []


def test_a_closed_segment_also_refuses_a_new_attestation(monkeypatch):
    server = _install(monkeypatch, _renamed_routes())
    client = _client()
    client.observe_rate_window(remaining=0, reset_epoch=100_000, retry_after=None)
    with pytest.raises(sfir9.TransportRefused):
        client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    assert server.seen == []


def test_the_decision_is_computed_from_headers_never_from_a_probe(monkeypatch):
    server = _install(monkeypatch, {})
    client = _client()
    client.observe_rate_window(remaining=0, reset_epoch=10, retry_after=None)
    assert server.seen == [], "observing the rate window must not send a request"


def test_the_wait_is_actually_slept_not_merely_announced():
    slept: list[int] = []
    client = _client(sleeper=slept.append)
    client.observe_rate_window(remaining=0, reset_epoch=30, retry_after=None)
    assert slept == [30]


def test_a_continue_decision_sleeps_for_nothing():
    slept: list[int] = []
    client = _client(sleeper=slept.append)
    client.observe_rate_window(remaining=100, reset_epoch=None, retry_after=None)
    assert slept == []


# --------------------------------------------------------- checkpoint handoff


def _handoff(client, **overrides):
    body = dict(
        protocol_digest=protocol.Protocol().digest(),
        frontier_digest="sha256:frontier",
        visited_digest="sha256:visited",
        candidate_accumulator_digest="sha256:candidates",
        previous_segment_digest=sfir9.SCHEMA,
    )
    body.update(overrides)
    return client.handoff(**body)


def test_the_handoff_carries_every_field_the_contract_names():
    handoff = _handoff(_client())
    for key in (
        "protocol_digest",
        "roster_digest",
        "selection_digest",
        "current_root_host_uuid",
        "canonical_address",
        "frontier_digest",
        "visited_digest",
        "candidate_accumulator_digest",
        "logical_request_count",
        "network_hop_count",
        "provider_charged_count",
        "provider_remaining",
        "provider_reset_epoch",
        "previous_segment_digest",
    ):
        assert key in handoff.as_dict()


def test_the_handoff_is_typed_and_not_a_view_of_checkpoint_storage():
    handoff = _handoff(_client())
    assert isinstance(handoff, sfir9.TransportHandoff)

    source = (NS / "tools/sfir9_transport.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source, "transport must not open checkpoint storage"
    assert "import sfir8_checkpoint" not in source, (
        "transport must not import the checkpoint module. It is pinned in the "
        "upstream manifest because its bytes are part of the freeze, which is a "
        "different thing from transport reading its internals."
    )
    # The pin exists, and it is the only mention.
    assert sum(1 for m in sfir9.UPSTREAM_MODULES if m.module == "sfir8_checkpoint") == 1


def test_the_roster_digest_cannot_be_overridden_at_handoff_time():
    """A checkpoint for a different roster must not be constructible here.

    The roster and selection digests come from how the transport was built, and
    `handoff()` has no parameter that could replace them -- so a segment cannot
    be labelled with a roster it did not traverse.
    """
    client = _client(roster_digest="sha256:roster-A")
    with pytest.raises(TypeError):
        client.handoff(
            protocol_digest="p",
            frontier_digest="f",
            visited_digest="v",
            candidate_accumulator_digest="c",
            previous_segment_digest="s",
            roster_digest="sha256:roster-B",
        )
    assert _handoff(client).roster_digest == "sha256:roster-A"


def test_the_selection_digest_is_the_one_the_transport_was_built_with():
    client = _client(selection_digest="sha256:selection-A")
    assert _handoff(client).selection_digest == "sha256:selection-A"
    assert (
        _handoff(_client(selection_digest="sha256:selection-B")).digest()
        != _handoff(client).digest()
    )


def test_two_rosters_produce_different_handoff_digests():
    a = _handoff(_client(roster_digest="sha256:roster-A"))
    b = _handoff(_client(roster_digest="sha256:roster-B"))
    assert a.digest() != b.digest()


def test_the_handoff_reports_the_counters_the_transport_actually_observed(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    handoff = _handoff(client)
    assert handoff.logical_request_count == 1
    assert handoff.network_hop_count == 2
    assert handoff.provider_charged_count == 2


def test_the_handoff_adds_exactly_what_the_sfir8_checkpoint_lacked():
    """Why an SFIR8 checkpoint is not simply passed around."""
    import sfir8_checkpoint as upstream_checkpoint

    sfir8_fields = set(upstream_checkpoint.Checkpoint.__dataclass_fields__)
    for field in sfir9.HANDOFF_FIELDS_SFIR8_LACKED:
        assert field not in sfir8_fields
        assert field in sfir9.TransportHandoff.__dataclass_fields__


def test_a_segment_closed_by_the_rate_window_says_so_in_its_handoff():
    client = _client()
    client.observe_rate_window(remaining=0, reset_epoch=100_000, retry_after=None)
    assert _handoff(client).disposition == sfir9.SEGMENT_CLOSE_RATE_WINDOW


def test_an_open_segment_is_not_labelled_closed():
    assert _handoff(_client()).disposition == "SEGMENT_OPEN"


# ------------------------------------------------- no result-aware behaviour


@pytest.mark.parametrize("forbidden", sorted(sfir9.FORBIDDEN_TRANSPORT_INPUTS))
def test_a_scientific_quantity_offered_to_transport_refuses(forbidden):
    with pytest.raises(sfir9.TransportRefused) as caught:
        sfir9.require_no_scientific_input({forbidden: 1}, "test")
    assert caught.value.code == sfir9.SCIENTIFIC_INPUT


def test_the_forbidden_list_names_what_the_ruling_names():
    assert {
        "candidate_count",
        "capacity_threshold",
        "document_eligibility",
        "lineage_yield",
        "tree_usefulness",
        "repository_popularity",
    } <= sfir9.FORBIDDEN_TRANSPORT_INPUTS


def test_the_get_path_refuses_a_result_aware_context(monkeypatch):
    server = _install(monkeypatch, _renamed_routes())
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.get(REPO_URL, context={"candidate_count": 400})
    assert caught.value.code == sfir9.SCIENTIFIC_INPUT
    assert server.seen == []


def test_the_handoff_path_refuses_a_result_aware_extra():
    with pytest.raises(sfir9.TransportRefused):
        _handoff(_client(), extra={"lineage_yield": 12})


def test_a_clean_context_passes_the_same_check(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.get(REPO_URL, context={"segment_index": 3})
    assert client.counters().logical_requests == 1


def test_transport_declares_no_capacity_vocabulary():
    """The words themselves do not belong in this layer."""
    source = (NS / "tools/sfir9_transport.py").read_text(encoding="utf-8")
    body = source.split('FORBIDDEN_TRANSPORT_INPUTS')[2]
    for word in ("MINIMUM_C", "MINIMUM_Q", "quota_for", "meets_criterion"):
        assert word not in body


# ---------------------------------------------------------- credential hygiene


def test_no_credential_material_reaches_the_receipt(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_thisvaluemustneverbeserialized")
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    receipt = client.receipt()
    serialized = json.dumps(receipt)
    assert "ghp_thisvaluemustneverbeserialized" not in serialized

    # The receipt names the headers it refuses to record, so that one declared
    # list is excluded before scanning for the header names themselves.
    scanned = json.dumps({k: v for k, v in receipt.items()
                          if k != "credential_headers_never_recorded"}).casefold()
    for header in sfir9.SECRET_HEADERS:
        assert header not in scanned, (
            f"{header!r} appears in the receipt outside the declared exclusion list"
        )


def test_the_receipt_names_the_headers_it_refuses_to_record():
    assert set(_client().receipt()["credential_headers_never_recorded"]) == set(
        sfir9.SECRET_HEADERS
    )


def test_the_receipt_omits_response_bodies(monkeypatch):
    """A body can carry anything; only its digest is evidence."""
    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    for entry in client.receipt()["logical_requests"]:
        assert "body" not in entry


# ------------------------------------------------------ upstream equivalence


def test_the_wrapper_reaches_the_same_repository_identity_as_the_upstream(monkeypatch):
    """Same fixtures, same numeric repository, same canonical address."""
    _install(monkeypatch, _renamed_routes())
    bare = upstream_transport.ManualRedirectTransport()
    bare.seed_remaining(5000)
    upstream_result = bare.resolve_canonical_address("old-org/old-name", "12345")

    _install(monkeypatch, _renamed_routes())
    client = _client()
    wrapped = client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    assert wrapped.observed_numeric_id == upstream_result["observed_repository_id"]
    assert wrapped.canonical_address == upstream_result["canonical_address"]
    assert wrapped.as_dict()["renamed"] == upstream_result["renamed"]


def test_the_wrapper_sees_the_same_response_sequence_as_the_upstream(monkeypatch):
    server_a = _install(monkeypatch, _renamed_routes())
    bare = upstream_transport.ManualRedirectTransport()
    bare.seed_remaining(5000)
    bare.resolve_canonical_address("old-org/old-name", "12345")
    upstream_urls = list(server_a.seen)

    server_b = _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")

    assert list(server_b.seen) == upstream_urls
    assert [hop.status for hop in client.hops] == [
        atom.status for request in bare.requests for atom in request.atoms
    ]


def test_the_wrapper_accounts_the_same_provider_charges_as_the_upstream(monkeypatch):
    _install(monkeypatch, _renamed_routes())
    bare = upstream_transport.ManualRedirectTransport()
    bare.seed_remaining(5000)
    bare.resolve_canonical_address("old-org/old-name", "12345")
    upstream_totals = bare.totals()

    _install(monkeypatch, _renamed_routes())
    client = _client()
    client.attest_root(catalogue_address="old-org/old-name", host_uuid="12345")
    counters = client.counters()

    assert counters.logical_requests == upstream_totals["logical_requests"]
    assert counters.network_hops == upstream_totals["network_hops"]
    assert counters.provider_charged_requests == upstream_totals["provider_charged"]


def test_the_wrapper_and_the_upstream_disagree_exactly_where_sfir9_narrows(monkeypatch):
    """The discrimination half. Agreement alone would prove nothing.

    Delegation makes the wrapper agree with the implementation by construction,
    so equivalence on permitted inputs is not evidence on its own. What makes the
    pair informative is that on the behaviour SFIR9 forbids they must *differ* --
    the upstream proceeds and the wrapper refuses. If both proceeded, the
    narrowing would exist only in the docstring.
    """
    routes = {
        "https://raw.githubusercontent.com/a/b": (200, _rate(4999), b"{}"),
    }
    _install(monkeypatch, routes)

    bare = upstream_transport.ManualRedirectTransport()
    bare.seed_remaining(5000)
    proceeded = bare.get("https://raw.githubusercontent.com/a/b")
    assert proceeded.status == 200, "the upstream is permissive, which is the point"

    _install(monkeypatch, routes)
    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.get("https://raw.githubusercontent.com/a/b")
    assert caught.value.code == sfir9.DISALLOWED_TARGET


def test_the_upstream_hands_back_an_address_the_wrapper_refuses_to_hand_back():
    """The second narrowing: an unproved address is available upstream, not here."""
    bare = upstream_transport.ManualRedirectTransport()
    assert bare.address_for("old-org/old-name") == "old-org/old-name"

    client = _client()
    with pytest.raises(sfir9.TransportRefused) as caught:
        client.address_for("old-org/old-name")
    assert caught.value.code == sfir9.UNPROVEN_IDENTITY


def test_the_wrapper_never_exposes_the_upstream_object():
    """A caller who could reach it could reach the wider behaviour."""
    client = _client()
    public = {name for name in dir(client) if not name.startswith("_")}
    assert "upstream" not in public
    assert all(
        not isinstance(
            getattr(client, name, None),
            upstream_transport.ManualRedirectTransport,
        )
        for name in public
    )
