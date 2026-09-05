"""Every path the controller reads or writes, in one place.

The layout is masterplan section 8 / ARENA_CONTRACT section 1. Tests point
``CampaignPaths`` at a temporary root, which is why nothing here reaches for
``NAMESPACE_ROOT`` at call time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.constants import NAMESPACE_ROOT

__all__ = ["CampaignPaths"]


@dataclass(frozen=True, slots=True)
class CampaignPaths:
    root: Path

    @classmethod
    def default(cls) -> CampaignPaths:
        return cls(root=NAMESPACE_ROOT)

    # ------------------------------------------------------------ inputs
    @property
    def source_manifest(self) -> Path:
        return self.root / "source_manifest.jsonl"

    @property
    def campaign_manifest(self) -> Path:
        return self.root / "campaign_manifest.json"

    @property
    def canary_selection(self) -> Path:
        return self.root / "canary_selection.json"

    @property
    def model_registry(self) -> Path:
        return self.root / "model_registry.json"

    @property
    def evaluator_registry(self) -> Path:
        return self.root / "evaluator_registry.json"

    # ------------------------------------------------------------ state
    @property
    def queue_dir(self) -> Path:
        return self.root / "queue"

    @property
    def queue_db(self) -> Path:
        return self.queue_dir / "campaign.sqlite"

    @property
    def receipts_dir(self) -> Path:
        return self.root / "receipts"

    @property
    def provider_receipts_dir(self) -> Path:
        return self.receipts_dir / "provider_receipts"

    @property
    def registry_updates_dir(self) -> Path:
        return self.receipts_dir / "registry-updates"

    @property
    def bundle_receipts_dir(self) -> Path:
        """D21: one publish receipt per model, naming the bytes in the bucket."""

        return self.receipts_dir / "bundles"

    @property
    def prompt_registry_dir(self) -> Path:
        return self.root / "prompt_registry"

    @property
    def waivers_dir(self) -> Path:
        return self.receipts_dir / "waivers"

    @property
    def authorizations_dir(self) -> Path:
        """Founder authorization receipts (ARENA_CONTRACT section 11 D6)."""

        return self.receipts_dir / "authorizations"

    @property
    def runtimes_dir(self) -> Path:
        return self.root / "runtimes"

    @property
    def events_log(self) -> Path:
        return self.receipts_dir / "events.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def frozen_outputs_dir(self) -> Path:
        return self.root / "frozen_outputs"

    @property
    def cost_dir(self) -> Path:
        return self.root / "cost"

    @property
    def pod_ledger(self) -> Path:
        return self.cost_dir / "pod_ledger.jsonl"

    @property
    def pod_provisioning_ledger(self) -> Path:
        """Create-time half of the pod ledger (ARENA_CONTRACT section 11 D2).

        ``pod_ledger.jsonl`` holds a pod's *billed life* and its schema
        (``arena/core/schemas/pod-ledger.schema.json``, lane A1) is closed and
        requires figures a pod does not have at creation. The provider API
        version, the redacted create payload and the authorization receipt are
        recorded here at the moment the pod is asked for, and are carried into
        the billed row later.
        """

        return self.cost_dir / "pod_provisioning.jsonl"

    @property
    def failures_dir(self) -> Path:
        return self.root / "failures"

    @property
    def errors_log(self) -> Path:
        return self.failures_dir / "errors.jsonl"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    # ------------------------------------------------------------ per model
    def model_run_dir(self, model_key: str) -> Path:
        return self.runs_dir / model_key

    def raw_dir(self, model_key: str) -> Path:
        return self.model_run_dir(model_key) / "raw"

    def canonical_dir(self, model_key: str) -> Path:
        return self.model_run_dir(model_key) / "canonical"

    def receipt_dir(self, model_key: str) -> Path:
        return self.model_run_dir(model_key) / "receipts"

    def run_summary(self, model_key: str) -> Path:
        return self.model_run_dir(model_key) / "run-summary.json"

    def canary_receipt(self, model_key: str) -> Path:
        return self.receipts_dir / f"canary-{model_key}.json"

    def registry_update(self, model_key: str) -> Path:
        return self.registry_updates_dir / f"{model_key}.json"

    def bundle_receipt(self, model_key: str) -> Path:
        """``receipts/bundles/<model_key>.json`` (ARENA_CONTRACT 11.5 D21)."""

        return self.bundle_receipts_dir / f"{model_key}.json"

    def canary_dir(self, model_key: str) -> Path:
        """``runs/<model_key>/canary/`` -- the canary's own page records."""

        return self.model_run_dir(model_key) / "canary"

    def canary_pages(self, model_key: str) -> Path:
        return self.canary_dir(model_key) / "pages.jsonl"

    def canary_driver_receipt(self, model_key: str) -> Path:
        """What the D20 driver did, including how the pod was returned."""

        return self.receipts_dir / f"canary-driver-{model_key}.json"

    def bootstrap_waiver(self, model_key: str) -> Path:
        return self.waivers_dir / f"{model_key}-bootstrap-full-run.json"

    def license_waiver(self, model_key: str) -> Path:
        """ARENA_CONTRACT section 11 D7."""

        return self.waivers_dir / f"license-{model_key}.json"

    def runtime_json(self, model_key: str) -> Path:
        return self.runtimes_dir / model_key / "runtime.json"

    def canary_provision_receipt(self, model_key: str) -> Path:
        return self.receipts_dir / f"canary-provision-{model_key}.json"

    def provision_gate_receipt(
        self,
        model_key: str,
        phase: str,
        *,
        shard_index: int | None = None,
        shard_count: int | None = None,
    ) -> Path:
        """Where this phase's provision gate receipt goes (D20, D85).

        One path per model was one file per model, so the Full Run overwrote
        the canary's gate receipt and every slice overwrote the one before
        it. The phase and the slice are part of the name now, because a
        receipt that a later run can silently replace is not evidence.
        """

        if phase == "phase1_canary":
            return self.canary_provision_receipt(model_key)
        stem = "full-run" if phase.startswith("phase2") else phase
        slice_tag = "" if shard_count is None else f"-s{shard_index}of{shard_count}"
        return self.receipts_dir / f"{stem}-provision-{model_key}{slice_tag}.json"

    def frozen_manifest(self, model_key: str) -> Path:
        return self.frozen_outputs_dir / model_key / "manifest.jsonl"

    def frozen_marker(self, model_key: str) -> Path:
        return self.frozen_outputs_dir / model_key / "FROZEN.json"

    def preflight_receipt(self, stamp: str) -> Path:
        return self.receipts_dir / f"preflight-{stamp}.json"

    @property
    def cleanup_receipt(self) -> Path:
        return self.evidence_dir / "cleanup_receipt.json"

    def ensure(self) -> None:
        """Create the directories the controller owns. Idempotent."""

        for directory in (
            self.queue_dir,
            self.receipts_dir,
            self.provider_receipts_dir,
            self.registry_updates_dir,
            self.bundle_receipts_dir,
            self.waivers_dir,
            self.authorizations_dir,
            self.runs_dir,
            self.frozen_outputs_dir,
            self.cost_dir,
            self.failures_dir,
            self.evidence_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
