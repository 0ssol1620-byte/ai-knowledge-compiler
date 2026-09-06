"""Build SFIR1's complete, fail-closed prior-identity authority.

This module is intentionally independent of the SFIR1 capacity probe.  It has
no import of ``sources_sfir1``, does not discover files, and never opens an
SFIR1 candidate or payload.  Its default inventory is a closed list of exact
historical artifacts and root declarations, each pinned by SHA-256.

Large acquisition artifacts are searched through a read-only memory map.  The
process therefore does not materialise their 100+ MiB payload trees merely to
recover identity strings.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "tavonel.sfir1.spent_identity_authority.v1"
REQUIRED_GENERATIONS = frozenset(
    {"V1", "V2", "V2R1", "V2R2", "V2R3", "V2R3R1", "V2R4", "SFI1", "SFI2", "SFI3"}
)


class SpentAuthorityRefused(RuntimeError):
    """The complete prior-identity set cannot be proved."""


def _entry(
    generation: str, role: str, path: str, sha256: str, kind: str = "json"
) -> dict[str, str]:
    return {
        "generation": generation,
        "role": role,
        "path": path,
        "sha256": "sha256:" + sha256,
        "kind": kind,
    }


# Closed, pre-SFIR1 inventory.  Do not replace this with glob/latest/newest.
# Root declarations conservatively reserve all historical source containers;
# the JSON artifacts contribute the exact looked-at, forensic, mutation,
# retrospective and reserved identities carried by the live V2R4/SFI3 chain.
DEFAULT_INVENTORY: tuple[dict[str, str], ...] = (
    _entry(
        "V2R4",
        "registry:root-identity",
        "research/tavonel_eval_v2/tools/root_identity.py",
        "650766c4b6267b89ba8b730fbae90c134bc5240c458a19362b63d0747c61ab9d",
        "root_registry",
    ),
    _entry(
        "V1",
        "roots:p4c",
        "research/tavonel_eval_v2/acquisition/sources_p4c.py",
        "f0503410304ed70c758cde592789cf1e9bcf081b452ec1d215f050d676ec0c96",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:p4e",
        "research/tavonel_eval_v2/acquisition/sources_p4e.py",
        "874b1737e27ae5aeab90437ad489925e9b53d51a1fc7be35b3e96e0f36be7465",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:p4g",
        "research/tavonel_eval_v2/acquisition/sources_p4g.py",
        "b8193e92d00ed1084d6d2403a6022c35ded8f835b8d6973dfd8de7ff6f4303a7",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:p4i",
        "research/tavonel_eval_v2/acquisition/sources_p4i.py",
        "81eee0d0f9b08fc6c2aa6bb9c618134e11b718de0f2b9e26bc44f7501ad6a7c9",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:sfh1",
        "research/tavonel_eval_v2/acquisition/sources_sfh1.py",
        "c7e7d8bf4606b959c0627ca236f09386b13fb9b46dc7be23a6445039a51247b6",
        "root_module",
    ),
    _entry(
        "SFI1",
        "roots:sfi1",
        "research/tavonel_eval_v2/acquisition/sources_sfi1.py",
        "1d844b1964176dbcade331fdb03d7a30afff14781dbe7449bc34ce7d168cfca8",
        "root_module",
    ),
    _entry(
        "SFI2",
        "roots:sfi2",
        "research/tavonel_eval_v2/acquisition/sources_sfi2.py",
        "163d5b9909ebd45baa2a00f6f5732a2b1a396ec85026c3ae5a85ddfe86796f7a",
        "root_module",
    ),
    _entry(
        "SFI3",
        "roots:sfi3",
        "research/tavonel_eval_v2/acquisition/sources_sfi3.py",
        "06aad153d43b5d579aeea839c2bc1c96dbbd9f287b1f1e7651742d8654987f0b",
        "root_module",
    ),
    _entry(
        "V2R1",
        "roots:v2r1",
        "research/tavonel_eval_v2/acquisition/sources_v2r1.py",
        "c4b504100aa04106a8c6a9a2ef30c037aa3ea0c6f9b0f21e65796ae252fcede5",
        "root_module",
    ),
    _entry(
        "V2R2",
        "roots:v2r2",
        "research/tavonel_eval_v2/acquisition/sources_v2r2.py",
        "0caf7cf4acf3aef83c53fd7c03047fc877638ac76b23af65634b685278977cd3",
        "root_module",
    ),
    _entry(
        "V2R3",
        "roots:v2r3",
        "research/tavonel_eval_v2/acquisition/sources_v2r3.py",
        "26aa683d0d1bad02329ac02e1c014415d859c160bd534dd990f568c860305038",
        "root_module",
    ),
    _entry(
        "V2R3R1",
        "roots:v2r3r1",
        "research/tavonel_eval_v2/acquisition/sources_v2r3r1.py",
        "2b6950ce86e15ce2bad3555258bb38da763232296d33ba5566b22b44b1d6f854",
        "root_module",
    ),
    _entry(
        "V2R4",
        "roots:v2r4",
        "research/tavonel_eval_v2/acquisition/sources_v2r4.py",
        "a3010167a2c0db03bf83a39bd08bcad42d7e60a958856b14af74fc56edf2b15e",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:vbc1",
        "research/tavonel_eval_v2/acquisition/sources_vbc1_probe.py",
        "7cf62f1ba4a9a90f03abdabd6bfd7511aca938061b311cfcb78ca8ce919146a7",
        "root_module",
    ),
    _entry(
        "V1",
        "roots:vbc2",
        "research/tavonel_eval_v2/acquisition/sources_vbc2.py",
        "652948d39f767a6e0e15ad78669e53f228f21d50458a00135ae2d9c1c632f40a",
        "root_module",
    ),
    _entry(
        "V2",
        "vbc2:frame",
        "research/tavonel_eval_v2/artifacts/development/vbc2_lineages.json",
        "b04ddb003803a7aa25f863b7ddcc0b8f41cff10a4715ad076951c520b1cdb429",
    ),
    _entry(
        "SFI1",
        "sfi1:frame",
        "research/tavonel_eval_v2/artifacts/development/sfi1_lineages.json",
        "84fe2c3b0f473af93ea6707fc7fc030ec8325f0b42b1fa5073d18889d193f4ba",
    ),
    _entry(
        "SFI1",
        "sfi1:acquisition",
        "research/tavonel_eval_v2/artifacts/development/sfi1/sfi1_acquisition.json",
        "3c902f61b7ddc756a1119d4e8f8af26b6fb637ccba21bdc41ce2f9f85e3f7144",
    ),
    _entry(
        "SFI2",
        "sfi2:frame",
        "research/tavonel_eval_v2/artifacts/development/sfi2_lineages.json",
        "ed7ee5e247e68aa8ecbf73b46c820de1e0906e13a0df19d4963b8f83c3091a8e",
    ),
    _entry(
        "SFI2",
        "sfi2:acquisition",
        "research/tavonel_eval_v2/artifacts/development/sfi2/sfi2_acquisition.json",
        "f568e47fb8597882de077980fdec11eb409a8492c409e18cc597094fb027cf0a",
    ),
    _entry(
        "SFI3",
        "sfi3:frame",
        "research/tavonel_eval_v2/artifacts/development/sfi3_lineages.json",
        "7c30657b7f0a356fcda7d597ab483985de628076e293535c12ba8beb3a278b26",
    ),
    _entry(
        "SFI3",
        "sfi3:acquisition",
        "research/tavonel_eval_v2/artifacts/development/sfi3/sfi3_acquisition.json",
        "d9e2d4bbbda5ae2c28af15fcebfac1a4a847b7da9f3eff44f0a7a45bc65772b6",
    ),
    _entry(
        "V2",
        "v2:universe",
        "research/tavonel_eval_v2/artifacts/development/v2_universe/v2_universe_candidates.json",
        "1491f2f3a401162d422236d16c1f37d6b848cdd115f0a7312e72a70972d5e56c",
    ),
    _entry(
        "V2R1",
        "v2r1:universe",
        "research/tavonel_eval_v2/artifacts/development/v2r1_universe/v2r1_universe_candidates.json",
        "9102f732741cd075e436df4e6628983b5e6317cfb3ec5e55e1c6df8faa97b62f",
    ),
    _entry(
        "V2R2",
        "v2r2:universe",
        "research/tavonel_eval_v2/artifacts/development/v2r2_universe/v2r2_universe_candidates.json",
        "4d0bcdb740f539222ff1e2d00005045c07cf48e230302c93c4066fbb67fcf6a7",
    ),
    _entry(
        "V2R3",
        "v2r3:universe",
        "research/tavonel_eval_v2/artifacts/development/v2r3_universe/v2r3_universe_candidates.json",
        "67ad8a11de69d3fbe1bc02c83b4233bcdbe7dc37b0ce413a50273865932e6ca7",
    ),
    _entry(
        "V2R3R1",
        "v2r3r1:universe",
        "research/tavonel_eval_v2/artifacts/development/v2r3r1_universe/v2r3r1_universe_candidates.json",
        "6a0cb10f7c232e94556d4ce4141cce2f0b4af496db425146f7caaa017ba9e197",
    ),
    _entry(
        "V2R4",
        "v2r4:universe",
        "research/tavonel_eval_v2/artifacts/development/v2r4_universe/v2r4_universe_candidates.json",
        "3423933e19a0c1201fdd95a8cbdfdb7cd8f90842b82eb79740e43e833317d764",
    ),
    _entry(
        "SFI2",
        "sfi2:forensic",
        "research/tavonel_eval_v2/receipts/sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d.json",
        "3aacb083f48d1ab2a5282255e82c679d7c37d9e8ccc22c0e7fc3d4be82f9b310",
    ),
    _entry(
        "V2",
        "identity:retrospective",
        "research/tavonel_eval_v2/receipts/identity-change-benchmark--20260824T092056Z-eb6269afcbd0.json",
        "0f2422542197ae1995ef69da088043bd23abd731b52c673dc915d8817f1dd0a6",
    ),
    _entry(
        "V2",
        "identity:mutation-differential",
        "research/tavonel_eval_v2/receipts/identity-quarantine-differential--20260825T022223Z-aeb7bfe3bbf9.json",
        "1f53322d96e67bea09458021603a9e1b815721b69be548665608f5280107511e",
    ),
    _entry(
        "V2R1",
        "v2r1:terminal",
        "research/tavonel_eval_v2/receipts/identity-change-migration-closure-v2r1--20260825T075028Z-fc54677a5d9a.json",
        "709ddc7146883e7f511cf446e404b55369a5fa549d2155715a5f31816ad349d6",
        "attestation",
    ),
    _entry(
        "V2R2",
        "v2r2:terminal",
        "research/tavonel_eval_v2/receipts/identity-change-migration-closure-v2r2--20260825T104800Z-c1041a14bdc3.json",
        "9e62c7a890de07736c6900b83f9d04a5ccbc06829b0fb917593b11800b5bfab3",
        "attestation",
    ),
    _entry(
        "V2R3",
        "v2r3:terminal",
        "research/tavonel_eval_v2/receipts/identity-change-migration-closure-v2r3-chain-disposition--20260825T204825Z-620d496e43b9.json",
        "ff326c8939ecef371adaa4a3bf0e9381e69ea08b000a05d9fec95eb5370498f5",
        "attestation",
    ),
    _entry(
        "V2R3R1",
        "v2r3r1:terminal",
        "research/tavonel_eval_v2/receipts/identity-change-migration-closure-v2r3r1--20260825T213041Z-f710e6b3d6f5.json",
        "11b772273bb700ddb114a98f94be3bfda6fad4c123ca9b6136ffc77806c84fba",
        "attestation",
    ),
    _entry(
        "V2R4",
        "v2r4:terminal",
        "research/tavonel_eval_v2/receipts/identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json",
        "28da167f1c98a67b866e40add4bfa5ba840b618e1a1559c24a11b516e2ea3474",
        "attestation",
    ),
    _entry(
        "SFI3",
        "sfi3:reservation",
        "research/tavonel_eval_v2/receipts/sfi3-root-reservation--20260826T040829Z-e0f676096927.json",
        "4ed7d2ea654fa89dbb63258ace3a4ea77eab8722e29c3218db351f30cde7a8f4",
        "attestation",
    ),
    _entry(
        "SFI3",
        "sfi3:freeze",
        "research/tavonel_eval_v2/receipts/sfi3-lineage-freeze--20260826T112657Z-c40e5b5a48be.json",
        "754c0ff204d311f69c5df3bc268fbdb4280061c77fe92a7e09e1236ac36c8270",
        "attestation",
    ),
    _entry(
        "SFI3",
        "sfi3:frame-verification",
        "research/tavonel_eval_v2/receipts/sfi3-frame-verification--20260826T120526Z-b4f647f6e883.json",
        "54291a2ccba0b7faee8be2bc554a4529b2f64d0cc0ad26a8f1ed91e8e9194287",
        "attestation",
    ),
)


_ID_PATTERN = re.compile(
    rb'"(?P<key>lineage_id|source_id|candidate_id|alias_id|redirect_alias|old_id|new_id)"\s*:\s*(?P<value>"(?:[^"\\]|\\.)*")'
)
_SCHEMA_PATTERN = re.compile(rb'"schema"\s*:\s*("(?:[^"\\]|\\.)*")')


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _normalised_aliases(identity: str) -> set[str]:
    aliases = {identity}
    if identity.startswith("ecfr:"):
        parts = identity.split(":")
        if len(parts) >= 4:
            aliases.add(f"ecfr:{int(parts[1])}:{parts[-1]}")
    elif identity.startswith("wikipedia:en:"):
        aliases.add("wiki:en:title:" + identity.removeprefix("wikipedia:en:").casefold())
    return aliases


def _json_identities(path: Path) -> tuple[str, set[str], set[str]]:
    lineages: set[str] = set()
    aliases: set[str] = set()
    with (
        path.open("rb") as handle,
        mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        schema_match = _SCHEMA_PATTERN.search(mapped)
        if schema_match is None:
            raise SpentAuthorityRefused(f"mandatory JSON has no schema: {path}")
        schema = json.loads(schema_match.group(1))
        if not isinstance(schema, str) or not schema.startswith("tavonel."):
            raise SpentAuthorityRefused(f"mandatory JSON has an invalid schema: {path}")
        for match in _ID_PATTERN.finditer(mapped):
            value = json.loads(match.group("value"))
            if not isinstance(value, str) or not value.strip():
                raise SpentAuthorityRefused(f"malformed identity in {path}")
            value = value.strip()
            key = match.group("key")
            if key in {b"alias_id", b"redirect_alias", b"old_id", b"new_id"}:
                aliases.update(_normalised_aliases(value))
            else:
                lineages.add(value)
                aliases.update(_normalised_aliases(value))
    # Small receipts often name forensic or retrospective cohorts as an array
    # under a semantically precise key rather than repeating ``lineage_id``.
    # Parse only those small files; acquisition trees stay mmap-only.
    if path.stat().st_size <= 5 * 1024 * 1024:
        raw = json.loads(path.read_text(encoding="utf-8"))

        def walk(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    folded = str(key).casefold().replace("-", "_")
                    identity_field = "lineage" in folded or folded in {
                        "source_ids",
                        "candidate_ids",
                        "aliases",
                        "redirects",
                    }
                    if identity_field and isinstance(child, list):
                        for item in child:
                            if isinstance(item, str) and item.strip():
                                lineages.add(item.strip())
                                aliases.update(_normalised_aliases(item.strip()))
                            elif isinstance(item, (Mapping, list)):
                                walk(item)
                    elif isinstance(child, (Mapping, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(raw)
    if not lineages and not aliases:
        raise SpentAuthorityRefused(f"mandatory JSON contributes no identity: {path}")
    return schema, lineages, aliases


def _json_schema(path: Path) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = raw.get("schema") if isinstance(raw, Mapping) else None
    if schema is None:
        raise SpentAuthorityRefused(f"mandatory attestation has no schema: {path}")
    if not isinstance(schema, str) or not schema.startswith("tavonel."):
        raise SpentAuthorityRefused(f"mandatory attestation has invalid schema: {path}")
    return schema


def _root_identities(root: Path, entry: Mapping[str, str]) -> tuple[set[str], dict[str, Any]]:
    ns = root / "research" / "tavonel_eval_v2"
    for path in (ns / "tools", ns / "acquisition"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import root_identity

    module_name = Path(entry["path"]).stem
    report = root_identity.read_module_roots(module_name)
    if not report["importable"] or report["unverifiable"]:
        raise SpentAuthorityRefused(f"root declaration is absent or ambiguous: {module_name}")
    rendered: set[str] = set()
    for identity in report["identities"]:
        rendered.add(":".join(identity))
        if identity[0] == "git" and len(identity) >= 3:
            rendered.add(f"git:{identity[1].casefold()}/{identity[2].casefold()}")
        elif identity[0] == "ecfr" and len(identity) >= 3:
            rendered.add(f"ecfr:{int(identity[1])}:{identity[2]}")
        elif identity[0] == "wikipedia" and len(identity) >= 2:
            category = identity[1].removeprefix("Category:").strip().casefold()
            rendered.add("wikipedia:en:category:" + "_".join(category.split()))
    return rendered, {"module": module_name, "root_count": len(rendered)}


def assemble_spent_authority(
    root: Path,
    generated_at: str,
    inventory: Sequence[Mapping[str, str]] = DEFAULT_INVENTORY,
) -> dict[str, Any]:
    """Return a protocol-compatible authority body without writing a receipt."""
    root = root.resolve()
    if not inventory:
        raise SpentAuthorityRefused("spent inventory is empty")
    roles = [entry.get("role") for entry in inventory]
    paths = [entry.get("path") for entry in inventory]
    if None in roles or len(roles) != len(set(roles)):
        raise SpentAuthorityRefused("spent inventory has an absent or ambiguous role")
    if None in paths or len(paths) != len(set(paths)):
        raise SpentAuthorityRefused("spent inventory has an absent or ambiguous path")
    generations = {entry.get("generation") for entry in inventory}
    missing = REQUIRED_GENERATIONS - generations
    extra = generations - REQUIRED_GENERATIONS
    if missing or extra:
        detail = f"missing={sorted(missing)} extra={sorted(extra)}"
        raise SpentAuthorityRefused(f"spent generations are incomplete or unknown: {detail}")

    containers: set[str] = set()
    lineages: set[str] = set()
    aliases: set[str] = set()
    refs: list[dict[str, str]] = []
    for entry in inventory:
        if set(entry) != {"generation", "role", "path", "sha256", "kind"}:
            raise SpentAuthorityRefused(
                f"inventory entry has an ambiguous shape: {entry.get('role')}"
            )
        path = (root / entry["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise SpentAuthorityRefused(
                f"spent source escapes repository: {entry['path']}"
            ) from error
        if not path.is_file():
            raise SpentAuthorityRefused(f"mandatory spent source is absent: {entry['path']}")
        actual = _sha(path)
        if actual != entry["sha256"]:
            raise SpentAuthorityRefused(f"mandatory spent source digest drift: {entry['path']}")
        if entry["kind"] == "root_module":
            roots, detail = _root_identities(root, entry)
            containers.update(roots)
            aliases.update(roots)
            schema = "tavonel.root_declaration.python.v1"
            if detail["module"] != path.stem:
                raise SpentAuthorityRefused(f"root module ambiguity: {entry['path']}")
        elif entry["kind"] == "root_registry":
            schema = "tavonel.root_identity.registry.python.v1"
        elif entry["kind"] == "json":
            schema, found_lineages, found_aliases = _json_identities(path)
            lineages.update(found_lineages)
            aliases.update(found_aliases)
            # The live probe's current container namespace is lineage-granular
            # for Git/eCFR.  Mirroring exact looked-at lineages here prevents a
            # container comparison from becoming weaker than its lineage check.
            containers.update(found_lineages)
            for identity in found_lineages:
                if identity.startswith("git:") and "/" in identity:
                    repo = identity.removeprefix("git:").split(":", 1)[0]
                    containers.add("git:" + repo.casefold())
                elif identity.startswith("ecfr:"):
                    parts = identity.split(":")
                    if len(parts) >= 4:
                        containers.add(f"ecfr:{int(parts[1])}:{parts[2]}")
        elif entry["kind"] == "attestation":
            schema = _json_schema(path)
        else:
            raise SpentAuthorityRefused(f"unknown spent source kind: {entry['kind']}")
        refs.append(
            {
                "generation": entry["generation"],
                "path": entry["path"],
                "sha256": actual,
                "schema": schema,
            }
        )

    if not containers or not lineages or not aliases:
        raise SpentAuthorityRefused(
            "complete spent authority must contain containers, lineages and aliases"
        )
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "container_ids": sorted(containers),
        "lineage_ids": sorted(lineages),
        "alias_ids": sorted(aliases),
        "sources": refs,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    body["content_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return body


def write_spent_authority(destination: Path, body: Mapping[str, Any]) -> Path:
    """Write once; existing authorities are never replaced."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
    except FileExistsError as error:
        raise SpentAuthorityRefused(f"spent authority already exists: {destination}") from error
    return destination


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    body = assemble_spent_authority(args.root, args.generated_at)
    path = write_spent_authority(args.destination, body)
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
