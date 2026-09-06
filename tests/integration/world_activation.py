"""The activation contract, modelled once and used by both end-to-end suites.

This is not PostgreSQL. Production activation is `promote_foundation_candidate`
with an advisory transaction lock and `FOR UPDATE`, and it has its own tests in
`supabase/tests/foundation_world_lifecycle.sql`.

What is modelled here is the part the *compile* path has to satisfy: activation
is explicit rather than a consequence of compiling, it is bound to the manifest
the actor believed was current, a candidate carrying open findings cannot be
activated at all, and the world being replaced is retained rather than
overwritten.

It lives in its own module because two suites need it and a second copy of an
activation rule is a second place for it to be wrong.
"""

from __future__ import annotations

from typing import Any


class ActivationRefused(RuntimeError):
    """A world was offered for activation and the store declined."""


class WorldStore:
    def __init__(self) -> None:
        self.versions: dict[str, dict[str, Any]] = {}
        self.active_manifest: str | None = None
        self.events: list[tuple[str, str]] = []

    def register(
        self,
        *,
        world_state_id: str,
        manifest_digest: str,
        artifacts: dict[str, Any],
        lifecycle: str,
        candidate_promotion: bool,
    ) -> None:
        if manifest_digest in self.versions:
            raise ActivationRefused("a candidate is immutable once registered")
        self.versions[manifest_digest] = {
            "world_state_id": world_state_id,
            "artifacts": artifacts,
            "lifecycle": lifecycle,
            "candidate_promotion": candidate_promotion,
            "status": "candidate",
        }

    def activate(
        self,
        *,
        manifest_digest: str,
        expected_current_manifest: str | None,
        actor: str,
        reason: str,
    ) -> None:
        if manifest_digest not in self.versions:
            raise ActivationRefused("no such candidate")
        version = self.versions[manifest_digest]
        if version["lifecycle"] != "candidate":
            # review_required and rejected are not activatable. The Core said as
            # much in the response; the store refuses independently rather than
            # trusting the caller to have read it.
            raise ActivationRefused(f"lifecycle {version['lifecycle']} is not activatable")
        if version["candidate_promotion"] is not False:
            raise ActivationRefused("a compile may not promote itself")
        if expected_current_manifest != self.active_manifest:
            # Optimistic concurrency. Somebody else activated between this actor
            # reading the world and deciding to replace it, and that change would
            # be silently lost.
            raise ActivationRefused("active world moved since it was read")
        if not reason.strip():
            raise ActivationRefused("activation requires a stated reason")
        if self.active_manifest is not None:
            self.versions[self.active_manifest]["status"] = "superseded"
        version["status"] = "active"
        self.active_manifest = manifest_digest
        self.events.append((actor, manifest_digest))

    def read(self, artifact_id: str) -> Any:
        """Read through the active pointer, the only way a reader sees a world."""
        if self.active_manifest is None:
            raise ActivationRefused("no active world")
        artifacts = self.versions[self.active_manifest]["artifacts"]
        return artifacts[artifact_id]
