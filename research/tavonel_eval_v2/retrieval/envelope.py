"""Queryable retrieval envelopes — a derived view over canonical atoms.

Founder ruling, 2026-08-22: **canonical granularity and retrieval granularity
are separate concerns**, and P4c-Core failed because this module did not exist.

Fine canonical atoms stay exactly as they are::

    § X.Y  →  (a)  →  (1)  →  (i)

Each remains the atom of stable identity, revision lineage, source evidence and
invalidation. Nothing here changes, replaces, merges or supersedes one. What
this module adds is a *second* addressing layer for natural-language retrieval,
because an enumeration marker like ``(a)`` or ``(3)`` carries no semantic intent
a person could have typed — which is precisely what P4c measured at 0.120
top-one on eCFR.

An envelope is a **derived retrieval artifact**, and five properties make that
claim checkable rather than decorative:

1. it records the logical ids of its members, so it is a pointer and not a copy;
2. source evidence traces through the envelope down to the child atoms;
3. a typed dependency edge invalidates the envelope when any member atom moves;
4. an answer or citation returns **fine atom** evidence, never envelope text;
5. it is never a source of truth — ``authoritative`` is ``False`` and stays so.

The last one is not a comment. ``EnvelopeIndex`` refuses to emit evidence from
envelope text, and the P4d gates check the refusal.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

# --- what an envelope is, and is not -----------------------------------------

DERIVED = "DERIVED_RETRIEVAL_ARTIFACT"
AUTHORITATIVE = "CANONICAL_ATOM"

#: The typed edge from an envelope to each atom it covers. Named, because an
#: untyped "contains" edge is how a derived view quietly becomes a fact.
COVERS = "covers_canonical_atom"

#: A heading that is only an enumeration marker cannot carry semantic intent.
#: This is the observation P4c produced, promoted to a declared rule.
_ENUMERATION_CHARS = set("()[].,: \t0123456789ivxlcdmIVXLCDMabcdefghijklmnopqrstuvwxyz")


def is_enumeration_marker(heading: str) -> bool:
    """True when a heading is an ordinal label rather than a name.

    ``(a)``, ``(3)``, ``(i)``, ``1.`` are markers. ``Definitions.`` is not.
    The test is deliberately conservative in one direction: a heading with any
    character outside the enumeration alphabet, or with more than three
    alphabetic characters in a row, is treated as a name. Misclassifying a name
    as a marker would silently coarsen retrieval, so the doubt runs the other
    way.
    """
    text = heading.strip()
    if not text:
        return True
    if not set(text) <= _ENUMERATION_CHARS:
        return False
    letters = "".join(c for c in text if c.isalpha())
    return len(letters) <= 3


class Envelope:
    """A named retrieval target covering one or more canonical atoms.

    ``member_ids`` is the whole substance of the object. Text is carried only
    to be indexed; it is not evidence and :meth:`evidence` refuses to return it.
    """

    __slots__ = ("envelope_id", "document_id", "revision", "anchor_path", "member_ids", "fields", "reason")

    def __init__(
        self,
        envelope_id: str,
        document_id: str,
        revision: str,
        anchor_path: str,
        member_ids: list[str],
        fields: dict[str, str],
        reason: str,
    ) -> None:
        self.envelope_id = envelope_id
        self.document_id = document_id
        self.revision = revision
        self.anchor_path = anchor_path
        self.member_ids = member_ids
        self.fields = fields
        self.reason = reason

    # -- the five properties, made checkable ---------------------------------

    @property
    def authoritative(self) -> bool:
        """Always False. An envelope never becomes a source of truth."""
        return False

    @property
    def kind(self) -> str:
        return DERIVED

    def edges(self) -> list[dict[str, str]]:
        """Typed dependency edges, one per member atom."""
        return [
            {"edge": COVERS, "from": self.envelope_id, "to": atom, "to_kind": AUTHORITATIVE}
            for atom in self.member_ids
        ]

    def evidence(self, atoms: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Return **fine atom** evidence for every member.

        Envelope text is never returned. A caller that wanted the envelope's own
        prose as an answer span would have to reach past this method, and the
        P4d gate checks that no returned record carries envelope-level text.
        """
        out: list[dict[str, Any]] = []
        for atom_id in self.member_ids:
            atom = atoms[atom_id]
            out.append(
                {
                    "atom_id": atom_id,
                    "kind": AUTHORITATIVE,
                    "explicit_path": atom["explicit_path"],
                    "text_sha256": atom["text_sha256"],
                    "via_envelope": self.envelope_id,
                    "envelope_is_evidence": False,
                }
            )
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "kind": self.kind,
            "authoritative": self.authoritative,
            "document_id": self.document_id,
            "revision": self.revision,
            "anchor_path": self.anchor_path,
            "member_ids": list(self.member_ids),
            "member_count": len(self.member_ids),
            "constructed_because": self.reason,
        }


# --- construction ------------------------------------------------------------

NAMED_ANCHOR = "named parent heading; children are enumeration markers"
SELF_CONTAINED = "heading is a name; the atom is self-contained"


def _atom_id(document_id: str, revision: str, path: str) -> str:
    return document_id + "|" + revision + "|" + path


def build_envelopes(
    document_id: str,
    revision: str,
    units: list[dict[str, Any]],
    fields: dict[str, str],
) -> tuple[list[Envelope], dict[str, dict[str, Any]]]:
    """Group canonical atoms into the minimal self-contained retrieval window.

    The rule is **structural and decided before any query is scored**:

    * an atom whose heading is a name is its own envelope;
    * an atom whose heading is an enumeration marker joins the envelope anchored
      at its nearest ancestor with a named heading, together with that
      ancestor's own text and its other enumerated descendants.

    Nothing about a question, a score or a retrieval outcome enters this
    function. It sees the document's structure and nothing else.
    """
    atoms: dict[str, dict[str, Any]] = {}
    for unit in units:
        path = "/".join(unit["explicit_path"])
        atoms[_atom_id(document_id, revision, path)] = {
            "explicit_path": unit["explicit_path"],
            "heading": unit.get("heading") or "",
            "text": unit.get("text") or "",
            "text_sha256": unit.get("text_sha256"),
            "path": path,
        }

    # nearest named ancestor, walking the explicit path from the leaf upward
    anchors: dict[str, list[str]] = {}
    anchor_of: dict[str, str] = {}
    for atom_id, atom in atoms.items():
        parts = list(atom["explicit_path"])
        anchor = None
        for depth in range(len(parts), 0, -1):
            candidate = parts[:depth]
            if not is_enumeration_marker(candidate[-1]):
                anchor = "/".join(candidate)
                break
        if anchor is None:
            # every level is an enumeration marker: the document root anchors it
            anchor = "/".join(parts[:1])
        anchor_of[atom_id] = anchor
        anchors.setdefault(anchor, []).append(atom_id)

    envelopes: list[Envelope] = []
    for anchor, members in anchors.items():
        members.sort(key=lambda a: atoms[a]["explicit_path"])
        digest = hashlib.sha256(anchor.encode("utf-8")).hexdigest()[:12]
        envelope_id = document_id + "|" + revision + "|env|" + digest
        anchor_heading = anchor.split("/")[-1]
        enumerated = [a for a in members if is_enumeration_marker(atoms[a]["heading"])]
        reason = NAMED_ANCHOR if enumerated else SELF_CONTAINED
        parents = [p for p in anchor.split("/")[:-1]]
        envelopes.append(
            Envelope(
                envelope_id=envelope_id,
                document_id=document_id,
                revision=revision,
                anchor_path=anchor,
                member_ids=members,
                fields={
                    "title": fields["title"],
                    "doc_type": fields["doc_type"],
                    "heading_path": anchor.replace("/", " "),
                    "heading": anchor_heading,
                    "body": "\n".join(atoms[a]["text"] for a in members),
                },
                reason=reason,
            )
        )
    envelopes.sort(key=lambda e: e.anchor_path)
    return envelopes, atoms


# --- invalidation ------------------------------------------------------------


def invalidated_envelopes(
    envelopes: Iterable[Envelope], moved_atom_ids: set[str]
) -> list[str]:
    """Envelopes whose derived state is stale because a member atom moved.

    This is the dependency direction that makes the envelope safe: a change is
    detected on the canonical atom, and the derived view is invalidated by it.
    The reverse — deciding an atom changed because an envelope's text changed —
    is never done, and no function here offers it.
    """
    return sorted(
        e.envelope_id for e in envelopes if moved_atom_ids & set(e.member_ids)
    )


def envelope_fingerprint(envelope: Envelope, atoms: dict[str, dict[str, Any]]) -> str:
    """A digest over member ids and member atom digests, never over prose.

    An envelope that fingerprinted its own concatenated text could drift from
    its members without either noticing.
    """
    payload = [
        [atom_id, atoms[atom_id]["text_sha256"]] for atom_id in envelope.member_ids
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- citation addressing -----------------------------------------------------


def normalise_citation(text: str) -> str:
    """Fold a source-native locator to a comparison key.

    ``§ 240.0-1(a)(3)``, ``240.0-1 (a)(3)`` and ``§240.0-1(a)(3)`` are the same
    address. Case, whitespace and the section sign carry no information.
    """
    return "".join(c for c in text.casefold() if c.isalnum())


def citation_for(atom: dict[str, Any]) -> str:
    """The source-native address of an atom, assembled from its explicit path.

    This is **not** answer leakage and the distinction is the founder's: an
    official citation is an address the source itself publishes and a reader
    already holds. It names *where* to look, never *what is written there*.
    """
    return "".join(str(part) for part in atom["explicit_path"])
