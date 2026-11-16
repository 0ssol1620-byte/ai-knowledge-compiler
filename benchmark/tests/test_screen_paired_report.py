from __future__ import annotations

import unittest
from typing import Any

from benchmark.screen.paired_report import INSUFFICIENT, build_report


def rec(
    stratum: str,
    cand: str,
    doc: str,
    *,
    n: int = 2,
    exact: int = 2,
    err: int = 0,
    cer: float = 0.1,
    fail: tuple[str, ...] = (),
    cost: float | None = 0.01,
) -> dict[str, Any]:
    return {
        "page_id": f"{doc}-p",
        "doc_id": doc,
        "stratum": stratum,
        "split": "dev",
        "candidate_id": cand,
        "revision": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "config_sha256": "c" * 64,
        "raw_sha256": "d" * 64,
        "metrics": {"cer": cer},
        "critical": {"n": n, "exact": exact, "accepted_errors": err},
        "hard_failures": list(fail),
        "gpu_seconds": None,
        "provider_cost_usd": cost,
        "latency_ms": 100,
    }


def docs(stratum: str, cand: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
    return [rec(stratum, cand, f"{stratum}{i}", **kw) for i in range(k)]


class PairedReportTest(unittest.TestCase):
    def test_disqualifying_error_beats_better_average(self) -> None:
        recs = docs("s", "inc", exact=1, cer=0.3) + docs("s", "cand", exact=2, cer=0.01)
        recs[-1]["critical"]["accepted_errors"] = 1
        r = build_report(recs, incumbent="inc")
        self.assertEqual(r["routes"]["s"]["primary"], "inc")
        self.assertIn("accepted_critical_errors=1", r["strata"]["s"]["rejected"]["cand"])

    def test_minority_winner_routed_only_in_its_stratum(self) -> None:
        recs: list[dict[str, Any]] = []
        for s in ("b", "c"):
            recs += docs(s, "inc", exact=2) + docs(s, "x", exact=1) + docs(s, "y", exact=1)
        recs += docs("a", "inc", exact=1) + docs("a", "x", exact=1) + docs("a", "y", exact=2)
        r = build_report(recs, incumbent="inc")
        self.assertEqual(r["routes"]["a"]["primary"], "y")
        for s in ("b", "c"):
            self.assertEqual(r["routes"][s]["primary"], "inc")
            self.assertNotIn("y", r["routes"][s]["alternatives"])

    def test_one_primary_per_stratum_and_alt_cap(self) -> None:
        recs = docs("s", "inc", exact=2)
        for c in ("p", "q", "r", "t"):
            recs += docs("s", c, exact=1)
        route = build_report(recs, incumbent="inc")["routes"]["s"]
        self.assertIsInstance(route["primary"], str)
        self.assertEqual(len(route["alternatives"]), 2)

    def test_empty_critical_is_insufficient_not_zero(self) -> None:
        recs = docs("s", "inc", n=0, exact=0) + docs("t", "inc", exact=2)
        r = build_report(recs, incumbent="inc")
        self.assertEqual(r["strata"]["s"]["cells"]["inc"]["critical_exact_rate"], INSUFFICIENT)
        self.assertIsNone(r["routes"]["s"]["primary"])
        self.assertEqual(r["summary"]["inc"]["strata_insufficient"], ["s"])

    def test_worst_stratum_shown_beside_macro(self) -> None:
        recs = docs("good", "inc", exact=2) + docs("bad", "inc", exact=1)
        s = build_report(recs, incumbent="inc")["summary"]["inc"]
        self.assertEqual(s["worst_stratum"], "bad")
        self.assertEqual(s["worst_stratum_critical_exact_rate"], 0.5)
        self.assertEqual(s["macro_critical_exact_rate"], 0.75)

    def test_failure_counted_and_unknown_cost_not_invented(self) -> None:
        recs = docs("s", "inc") + docs("s", "c", k=4)
        recs.append(rec("s", "c", "s9", exact=0, fail=("provider_unavailable",), cost=None))
        cell = build_report(recs, incumbent="inc")["strata"]["s"]["cells"]["c"]
        self.assertEqual(cell["failures"], 1)
        self.assertIsNone(cell["cost_per_accepted_page_usd"])

    def test_failed_pages_cannot_win_selection(self) -> None:
        f = ("provider_unavailable",)
        recs = [*docs("s", "inc", k=10, exact=1, n=2), rec("s", "c", "ok")]
        recs += [rec("s", "c", f"f{i}", n=0, exact=0, fail=f, cost=None) for i in range(9)]
        recs += [rec("s", "dead", "d0", n=0, exact=0, fail=("contract_failed",), cost=None)]
        r = build_report(recs, incumbent="inc")
        self.assertEqual(r["routes"]["s"]["primary"], "inc")
        self.assertNotIn("dead", r["routes"]["s"]["alternatives"])
        self.assertEqual(r["strata"]["s"]["rejected"]["dead"], "no_accepted_pages")

    def test_summary_worst_stratum_counts_failed_pages(self) -> None:
        f = ("provider_unavailable",)
        for fn in (2, 0):
            recs = docs("a", "c", k=10, exact=1)
            recs += [rec("b", "c", "ok")]
            recs += [rec("b", "c", f"f{i}", n=fn, exact=0, fail=f, cost=None) for i in range(9)]
            c = build_report(recs, incumbent="inc")["summary"]["c"]
            self.assertEqual(c["worst_stratum"], "b")
            self.assertAlmostEqual(c["worst_stratum_critical_exact_rate"], 0.1)

    def test_pairing_counts_discordant_docs(self) -> None:
        recs = docs("s", "inc", exact=1) + docs("s", "c", exact=2)
        p = build_report(recs, incumbent="inc")["strata"]["s"]["paired_vs_incumbent"]["c"]
        self.assertEqual((p["candidate_only_exact"], p["incumbent_only_exact"]), (5, 0))


if __name__ == "__main__":
    unittest.main()
