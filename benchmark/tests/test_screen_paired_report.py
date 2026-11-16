from __future__ import annotations

import copy
import math
import unittest
from typing import Any

from akc_absorption.metrics import _SplitMix64

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

    def test_fully_failed_stratum_is_worst_not_hidden(self) -> None:
        f = ("provider_unavailable",)
        for fn in (2, 0):
            recs = docs("a", "c", k=10)
            recs += [rec("b", "c", f"f{i}", n=fn, exact=0, fail=f, cost=None) for i in range(10)]
            c = build_report(recs, incumbent="inc")["summary"]["c"]
            self.assertEqual(
                (c["worst_stratum"], c["worst_stratum_critical_exact_rate"]), ("b", 0.0)
            )
            self.assertEqual(c["macro_critical_exact_rate"], 0.5)
            self.assertEqual(c["strata_insufficient"], [])
        # Accepted pages without critical fields do not hide the failed ones.
        recs = docs("a", "c", k=10) + [rec("b", "c", f"ok{i}", n=0, exact=0) for i in range(5)]
        recs += [rec("b", "c", f"f{i}", exact=0, fail=f, cost=None) for i in range(5)]
        c = build_report(recs, incumbent="inc")["summary"]["c"]
        self.assertEqual((c["worst_stratum"], c["worst_stratum_critical_exact_rate"]), ("b", 0.0))

    def test_failing_a_bad_page_does_not_raise_the_rate(self) -> None:
        # Page x is accepted but 0/5 exact; failing it must not look better than reading it.
        recs = [rec("s", "c", "ok"), rec("s", "c", "x", n=5, exact=0)]
        before = build_report(recs, incumbent="c")["strata"]["s"]["cells"]["c"]["selection_rate"]
        recs[1]["hard_failures"] = ["provider_unavailable"]
        after = build_report(recs, incumbent="c")["strata"]["s"]["cells"]["c"]["selection_rate"]
        self.assertLessEqual(after, before)

    def test_out_of_range_critical_counts_refused(self) -> None:
        for n, exact in ((2, 3), (2, -1), (-1, 0)):
            with self.assertRaises(ValueError):
                build_report([rec("s", "c", "d", n=n, exact=exact)], incumbent="c")

    def test_property_failing_a_page_never_improves_its_candidate(self) -> None:
        """Fuzz: turning any one accepted page into a hard failure never improves its
        candidate's stratum rate, macro, worst stratum or primary route."""

        def rate(x: Any) -> float:
            return math.inf if x in (INSUFFICIENT, None) else float(x)

        def subset(items: list[str]) -> list[str]:
            mask = 1 + g.below(2 ** len(items) - 1)
            return [x for k, x in enumerate(items) if mask >> k & 1]

        g = _SplitMix64(20261116)
        for _ in range(400):
            recs = []
            for s in subset(["a", "b", "c"]):
                for cand in subset(["inc", "c1", "c2"]):
                    for d in range(1 + g.below(3)):
                        for p in range(1 + g.below(3)):
                            n = g.below(5)
                            r = rec(s, cand, f"{s}{d}", n=n, exact=g.below(n + 1))
                            r["page_id"] = f"{s}{cand}{d}-{p}"
                            r["metrics"]["cer"] = g.below(1000) / 1000
                            if g.below(10) < 3:
                                r["hard_failures"] = ["provider_unavailable"]
                            recs.append(r)
            ok = [i for i, r in enumerate(recs) if not r["hard_failures"]]
            if not ok:
                continue
            i = ok[g.below(len(ok))]
            worse = copy.deepcopy(recs)
            worse[i]["hard_failures"] = ["contract_failed"]
            c, s = recs[i]["candidate_id"], recs[i]["stratum"]
            b, a = build_report(recs, incumbent="inc"), build_report(worse, incumbent="inc")
            ctx = (recs, i)
            cell_b, cell_a = b["strata"][s]["cells"][c], a["strata"][s]["cells"][c]
            self.assertLessEqual(
                rate(cell_a["selection_rate"]), rate(cell_b["selection_rate"]), ctx
            )
            sb, sa = b["summary"][c], a["summary"][c]
            for key in ("macro_critical_exact_rate", "worst_stratum_critical_exact_rate"):
                self.assertLessEqual(rate(sa[key]), rate(sb[key]) + 1e-12, (key, ctx))
            self.assertLessEqual(set(sa["strata_insufficient"]), set(sb["strata_insufficient"]))
            if a["routes"][s]["primary"] == c:
                self.assertEqual(b["routes"][s]["primary"], c, ctx)

    def test_pairing_counts_discordant_docs(self) -> None:
        recs = docs("s", "inc", exact=1) + docs("s", "c", exact=2)
        p = build_report(recs, incumbent="inc")["strata"]["s"]["paired_vs_incumbent"]["c"]
        self.assertEqual((p["candidate_only_exact"], p["incumbent_only_exact"]), (5, 0))


if __name__ == "__main__":
    unittest.main()
