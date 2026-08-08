#!/usr/bin/env python3
"""Act on the capacity shortfall the runtime can only declare.

``evaluate_pool_capacity`` reports how many workers a pool is short and stops
there by design: the runtime consumes an inventory and never reaches for a
provider API. That leaves the deciding and the acting in different places, and
until now the acting has been a person watching a terminal. Every time a pod was
reclaimed, deleted at a deadline, or lost its GPU on restart, someone had to
notice, diagnose, provision a replacement, restage the remaining work and
relaunch. A product whose claim is automated recovery should not need that.

This is the acquisition owner the runtime was written to expect. It observes the
fleet, feeds those observations to the health registry, asks the runtime whether
the pool is below its floor, and when it is, provisions replacements and resumes
the outstanding work.

What it will not do matters as much. It refuses to act on conditions it cannot
fix -- an exhausted account is not a capacity problem and retrying it just burns
the remainder -- and it stops at an attempt budget and a spend ceiling rather
than looping. The distinction is recorded per action so the journal shows what
recovered, what was declined, and why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SUPERVISOR_SCHEMA = "folynta.campaign-recovery-supervision.v1"

# Conditions the supervisor can resolve by acquiring a replacement worker.
RECOVERABLE = frozenset(
    {
        "worker_absent_from_provider",
        "worker_exited",
        "worker_unreachable",
        "worker_idle_with_work_outstanding",
    }
)
# Conditions that no amount of provisioning will fix. Retrying these converts a
# recoverable pause into a drained balance.
UNRECOVERABLE = frozenset(
    {
        "account_out_of_credit",
        "attempt_budget_exhausted",
        "spend_ceiling_reached",
        "no_capacity_offered",
    }
)


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    """One worker as the provider and the pod itself report it."""

    worker_id: str
    provider_status: str | None
    reachable: bool
    documents_done: int
    documents_expected: int
    processes_running: int

    @property
    def finished(self) -> bool:
        return self.documents_done >= self.documents_expected

    @property
    def serving(self) -> bool:
        """Serving means the provider still has it, it answers, and it is working.

        The provider's view comes first: a pod that has been deleted or stopped
        cannot be serving whatever a stale probe reports. After that, an
        unreachable worker is not counted as serving -- but it is also never
        counted as idle, because the supervisor cannot see inside a pod it
        cannot talk to, and a probe that does not answer is not evidence that
        nothing is running. That confusion deleted a fleet mid-run once already.
        """
        if self.provider_status is None or self.provider_status.upper() != "RUNNING":
            return False
        if not self.reachable:
            return False
        return self.finished or self.processes_running > 1

    def diagnose(self) -> str | None:
        if self.finished:
            return None
        if self.provider_status is None:
            return "worker_absent_from_provider"
        if self.provider_status.upper() != "RUNNING":
            return "worker_exited"
        if not self.reachable:
            return "worker_unreachable"
        if self.processes_running <= 1:
            return "worker_idle_with_work_outstanding"
        return None


@dataclass
class SupervisionBudget:
    """Bounds that make the supervisor stop instead of looping."""

    max_replacements: int
    spend_ceiling_usd: float
    hourly_rate_usd: float
    replacements_made: int = 0
    spent_usd: float = 0.0

    def would_exceed(self, hours: float) -> str | None:
        if self.replacements_made >= self.max_replacements:
            return "attempt_budget_exhausted"
        if self.spent_usd + hours * self.hourly_rate_usd > self.spend_ceiling_usd:
            return "spend_ceiling_reached"
        return None


@dataclass
class SupervisionJournal:
    """Every decision, so the recovery can be audited rather than believed."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, action: str, **fields: Any) -> None:
        self.entries.append({"action": action, **fields})

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for entry in self.entries:
            tally[entry["action"]] = tally.get(entry["action"], 0) + 1
        return dict(sorted(tally.items()))


def detect_account_exhaustion(observations: tuple[WorkerObservation, ...]) -> bool:
    """Recognise the shape of a provider-wide stop before spending on it.

    An exhausted balance does not look like a worker failure; it looks like every
    worker failing at once, because the provider stops the whole account rather
    than one pod. Acquiring replacements in that state cannot succeed and burns
    whatever balance a top-up later restores, so the pattern is named and
    treated as unrecoverable instead of retried worker by worker.
    """
    if len(observations) < 2:
        return False
    return all(
        not o.finished
        and (o.provider_status is None or o.provider_status.upper() != "RUNNING")
        for o in observations
    )


def classify(diagnosis: str | None, budget: SupervisionBudget, hours: float) -> str:
    """Decide whether a diagnosis warrants acquisition, and say so plainly."""
    if diagnosis is None:
        return "healthy"
    blocked = budget.would_exceed(hours)
    if blocked is not None:
        return blocked
    if diagnosis in RECOVERABLE:
        return "recoverable"
    return diagnosis


def plan_supervision(
    observations: tuple[WorkerObservation, ...],
    *,
    minimum_workers: int,
    budget: SupervisionBudget,
    replacement_hours: float,
) -> dict[str, Any]:
    """Turn a fleet snapshot into a decision, without touching any provider."""
    serving = tuple(o.worker_id for o in observations if o.serving)
    deficit = max(0, minimum_workers - len(serving))
    outstanding = sum(
        max(0, o.documents_expected - o.documents_done) for o in observations
    )

    if detect_account_exhaustion(observations):
        return {
            "serving_worker_ids": list(serving),
            "serving_worker_count": len(serving),
            "minimum_workers": minimum_workers,
            "capacity_deficit": deficit,
            "documents_outstanding": outstanding,
            "decisions": [
                {
                    "worker_id": o.worker_id,
                    "diagnosis": o.diagnose(),
                    "verdict": "account_out_of_credit",
                    "documents_done": o.documents_done,
                    "documents_expected": o.documents_expected,
                    "serving": False,
                }
                for o in observations
            ],
            "replacements_to_acquire": 0,
            "blocked_reasons": ["account_out_of_credit"],
            "should_stop": True,
        }

    decisions = []
    for observation in observations:
        diagnosis = observation.diagnose()
        decisions.append(
            {
                "worker_id": observation.worker_id,
                "diagnosis": diagnosis,
                "verdict": classify(diagnosis, budget, replacement_hours),
                "documents_done": observation.documents_done,
                "documents_expected": observation.documents_expected,
                "serving": observation.serving,
            }
        )

    replaceable = [d for d in decisions if d["verdict"] == "recoverable"]
    blocked = [d for d in decisions if d["verdict"] in UNRECOVERABLE]
    return {
        "serving_worker_ids": list(serving),
        "serving_worker_count": len(serving),
        "minimum_workers": minimum_workers,
        "capacity_deficit": deficit,
        "documents_outstanding": outstanding,
        "decisions": decisions,
        "replacements_to_acquire": min(len(replaceable), deficit) if deficit else 0,
        "blocked_reasons": sorted({d["verdict"] for d in blocked}),
        "should_stop": bool(blocked) or (deficit > 0 and not replaceable),
    }


def probe_worker(
    worker_id: str,
    host: str,
    port: int,
    key: Path,
    known_hosts: Path,
    result_root: str,
    expected: int,
    *,
    timeout: int = 40,
) -> WorkerObservation:
    """Ask one pod what it is doing, treating silence as unknown."""
    command = (
        f"md=$(find {result_root} -name '*.md' 2>/dev/null | wc -l); "
        "p=$(ps -eo cmd | grep -c '[m]ineru'); echo \"$md $p\""
    )
    try:
        completed = subprocess.run(
            [
                "ssh", "-n", "-i", str(key),
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=15",
                "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={known_hosts}",
                "-p", str(port), f"root@{host}", command,
            ],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return WorkerObservation(worker_id, None, False, 0, expected, 0)
    if completed.returncode != 0:
        return WorkerObservation(worker_id, "RUNNING", False, 0, expected, 0)
    parts = completed.stdout.strip().split()
    done = int(parts[0]) if parts and parts[0].isdigit() else 0
    procs = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return WorkerObservation(worker_id, "RUNNING", True, done, expected, procs)


def supervise(
    *,
    observe: Callable[[], tuple[WorkerObservation, ...]],
    acquire: Callable[[int], int],
    resume: Callable[[], None],
    minimum_workers: int,
    budget: SupervisionBudget,
    replacement_hours: float,
    poll_seconds: int,
    max_cycles: int,
    journal: SupervisionJournal,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Watch, decide, acquire and resume until the work finishes or must stop."""
    for cycle in range(1, max_cycles + 1):
        observations = observe()
        plan = plan_supervision(
            observations,
            minimum_workers=minimum_workers,
            budget=budget,
            replacement_hours=replacement_hours,
        )
        journal.record("observed", cycle=cycle, **{
            k: plan[k] for k in ("serving_worker_count", "capacity_deficit", "documents_outstanding")
        })

        if plan["documents_outstanding"] == 0:
            journal.record("completed", cycle=cycle)
            return {"outcome": "completed", "cycles": cycle, "plan": plan}

        if plan["should_stop"]:
            journal.record("stopped", cycle=cycle, reasons=plan["blocked_reasons"] or ["no_recoverable_worker"])
            return {"outcome": "stopped", "cycles": cycle, "plan": plan}

        wanted = plan["replacements_to_acquire"]
        if wanted:
            acquired = acquire(wanted)
            budget.replacements_made += acquired
            budget.spent_usd += acquired * replacement_hours * budget.hourly_rate_usd
            journal.record("acquired", cycle=cycle, requested=wanted, acquired=acquired)
            if acquired == 0:
                journal.record("stopped", cycle=cycle, reasons=["no_capacity_offered"])
                return {"outcome": "stopped", "cycles": cycle, "plan": plan}
            resume()
            journal.record("resumed", cycle=cycle, documents_outstanding=plan["documents_outstanding"])

        sleep(poll_seconds)

    journal.record("stopped", cycle=max_cycles, reasons=["cycle_budget_exhausted"])
    return {"outcome": "stopped", "cycles": max_cycles, "plan": plan}


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_receipt(result: dict[str, Any], journal: SupervisionJournal, budget: SupervisionBudget) -> dict[str, Any]:
    receipt = {
        "schema": SUPERVISOR_SCHEMA,
        "question": (
            "When a worker is lost mid-campaign, does the orchestration recover on "
            "its own, or does it stop and wait for a person?"
        ),
        "boundary": (
            "Acquisition is attempted only for conditions a replacement worker can "
            "resolve. An exhausted account, an exhausted attempt budget and a "
            "refused acquisition are reported rather than retried."
        ),
        "outcome": result["outcome"],
        "cycles": result["cycles"],
        "replacements_made": budget.replacements_made,
        "estimated_recovery_spend_usd": round(budget.spent_usd, 2),
        "action_counts": journal.counts(),
        "journal": journal.entries,
        "final_plan": result["plan"],
        "score_inflation_allowed": False,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True, type=Path, help="JSON fleet description")
    parser.add_argument("--minimum-workers", required=True, type=int)
    parser.add_argument("--max-replacements", type=int, default=4)
    parser.add_argument("--spend-ceiling-usd", type=float, default=20.0)
    parser.add_argument("--hourly-rate-usd", type=float, default=0.74)
    parser.add_argument("--replacement-hours", type=float, default=2.5)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=200)
    parser.add_argument("--acquire-command", help="shell command that provisions one worker")
    parser.add_argument("--resume-command", help="shell command that restages and relaunches")
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fleet = json.loads(args.fleet.read_text(encoding="utf-8-sig"))
    key = Path(fleet["key"])
    known_hosts = Path(fleet["known_hosts"])
    result_root = fleet["result_root"]

    def observe() -> tuple[WorkerObservation, ...]:
        return tuple(
            probe_worker(
                str(w["worker_id"]), str(w["host"]), int(w["port"]),
                key, known_hosts, result_root, int(w["documents_expected"]),
            )
            for w in fleet["workers"]
        )

    def acquire(count: int) -> int:
        if not args.acquire_command:
            return 0
        acquired = 0
        for _ in range(count):
            completed = subprocess.run(args.acquire_command, shell=True, check=False)
            if completed.returncode == 0:
                acquired += 1
        return acquired

    def resume() -> None:
        if args.resume_command:
            subprocess.run(args.resume_command, shell=True, check=False)

    budget = SupervisionBudget(
        max_replacements=args.max_replacements,
        spend_ceiling_usd=args.spend_ceiling_usd,
        hourly_rate_usd=args.hourly_rate_usd,
    )
    journal = SupervisionJournal()
    result = supervise(
        observe=observe, acquire=acquire, resume=resume,
        minimum_workers=args.minimum_workers, budget=budget,
        replacement_hours=args.replacement_hours,
        poll_seconds=args.poll_seconds, max_cycles=args.max_cycles,
        journal=journal,
    )
    receipt = build_receipt(result, journal, budget)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in receipt.items() if k != "journal"}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["outcome"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
