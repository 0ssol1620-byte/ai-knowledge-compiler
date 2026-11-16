from __future__ import annotations

import copy
import itertools
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

    def test_cell_critical_rate_and_ci_count_failed_pages(self) -> None:
        f = ("provider_unavailable",)

        def stratum(recs: list[dict[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = build_report(recs, incumbent="c")["strata"]["s"]
            return out

        # A1: failing the 0/5 page must not lift the field rate or its Wilson upper bound.
        recs = [rec("s", "c", "ok"), rec("s", "c", "x", n=5, exact=0)]
        before = stratum(recs)["cells"]["c"]
        recs[1]["hard_failures"] = list(f)
        after = stratum(recs)["cells"]["c"]
        self.assertLessEqual(after["critical_exact_rate"], before["critical_exact_rate"])
        self.assertLessEqual(after["critical_exact_ci"][1], before["critical_exact_ci"][1])
        # A2: nine of ten pages failed is a 0.1 cell, not a perfect one.
        recs = [rec("s", "c", "ok")] + [rec("s", "c", f"f{i}", exact=0, fail=f) for i in range(9)]
        self.assertAlmostEqual(stratum(recs)["cells"]["c"]["critical_exact_rate"], 0.1)
        # A3: all failed reports 0.0 with an interval, and is still not eligible.
        for fn in (2, 0):
            recs = [rec("s", "c", f"f{i}", n=fn, exact=0, fail=f) for i in range(3)]
            got = stratum(recs)
            self.assertEqual(got["cells"]["c"]["critical_exact_rate"], 0.0)
            self.assertNotEqual(got["cells"]["c"]["critical_exact_ci"], INSUFFICIENT)
            self.assertEqual(got["rejected"]["c"], "no_accepted_pages")
        # Paired: a failure written with n=0 still counts the gold n another candidate
        # recorded for that page, so 9 of 10 failed pages is 0.1, not 1.0.
        recs = [rec("s", "inc", f"d{i}", n=10, exact=9) for i in range(10)]
        recs += [rec("s", "c", "d0", n=10, exact=10)]
        recs += [rec("s", "c", f"d{i}", n=0, exact=0, fail=f) for i in range(1, 10)]
        cells = build_report(recs, incumbent="inc")["strata"]["s"]["cells"]
        self.assertAlmostEqual(cells["c"]["critical_exact_rate"], 0.1)
        self.assertAlmostEqual(cells["inc"]["critical_exact_rate"], 0.9)
        # Failed pages carrying critical n never make an accepted-n-less cell eligible.
        recs = [rec("s", "c", "ok", n=0, exact=0), rec("s", "c", "f", exact=0, fail=f)]
        self.assertEqual(stratum(recs)["rejected"]["c"], INSUFFICIENT)

    def test_added_failed_pages_cannot_win_a_tie_break(self) -> None:
        f = ("provider_unavailable",)
        base = [rec("a", "inc", "d1", exact=0, cer=0.5), rec("a", "c", "d1", exact=0, cer=0.6)]
        plus = base + [rec("a", "c", f"f{i}", exact=0, cer=0.0, fail=f) for i in range(3)]
        for recs in (base, plus):
            self.assertEqual(build_report(recs, incumbent="inc")["routes"]["a"]["primary"], "inc")

    def test_out_of_range_critical_counts_refused(self) -> None:
        for n, exact in ((2, 3), (2, -1), (-1, 0)):
            with self.assertRaises(ValueError):
                build_report([rec("s", "c", "d", n=n, exact=exact)], incumbent="c")

    def test_fuzz_malformed_records_fail_closed_with_value_error(self) -> None:
        """Any malformed field is refused with ValueError; nothing else leaks, and
        whatever is accepted yields finite rates inside [0, 1]."""
        odd: list[Any] = [0, 1, 2, 2.5, True, False, math.inf, -math.inf, math.nan]
        odd += [-1, None, "2", 10**18, [], {}]
        fields = [
            ("critical", "n"),
            ("critical", "exact"),
            ("critical", "accepted_errors"),
            ("metrics", "cer"),
            ("provider_cost_usd",),
            ("latency_ms",),
            ("hard_failures",),
            ("stratum",),
            ("candidate_id",),
            ("doc_id",),
            ("page_id",),
            ("critical",),
            ("metrics",),
        ]
        g = _SplitMix64(4242)
        for _ in range(3000):
            r = rec("s", "c", "d")
            if g.below(2):
                r["hard_failures"] = ["provider_unavailable"]
            for _k in range(1 + g.below(3)):
                *parents, leaf = fields[g.below(len(fields))]
                holder: Any = r
                for key in parents:
                    holder = holder.get(key) if isinstance(holder, dict) else None
                if not isinstance(holder, dict):
                    continue
                if g.below(8) == 0:
                    holder.pop(leaf, None)
                else:
                    holder[leaf] = copy.deepcopy(odd[g.below(len(odd))])
            try:
                out = build_report([r, rec("s", "c", "e")], incumbent="c")
            except ValueError:
                continue
            for st in out["strata"].values():
                for cell, key in itertools.product(
                    st["cells"].values(), ("selection_rate", "critical_exact_rate")
                ):
                    v = cell[key]
                    self.assertTrue(v == INSUFFICIENT or 0.0 <= v <= 1.0, (key, v, r))

    def test_property_failing_a_page_never_improves_its_candidate(self) -> None:
        """Fuzz: failing accepted pages or adding failed ones never improves the
        candidate's cell rates, Wilson upper bound, macro, worst stratum or primary."""

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
            c = recs[i]["candidate_id"]
            # Also fail more of c's pages, and add brand-new failed pages for c (any
            # recorded n, any CER): neither may help c anywhere.
            for r in worse:
                if r["candidate_id"] == c and g.below(3) == 0:
                    r["hard_failures"] = ["contract_failed"]
            strata_b = sorted({r["stratum"] for r in recs})
            for k in range(g.below(3)):
                new = rec(strata_b[g.below(len(strata_b))], c, f"new{k}", n=g.below(4), exact=0)
                new["page_id"], new["hard_failures"] = f"new-{k}", ["provider_unavailable"]
                new["metrics"]["cer"] = g.below(1000) / 1000
                worse.append(new)
            b, a = build_report(recs, incumbent="inc"), build_report(worse, incumbent="inc")
            ctx = (recs, worse)
            for s in strata_b:
                cell_b, cell_a = b["strata"][s]["cells"].get(c), a["strata"][s]["cells"].get(c)
                if cell_b is not None:
                    for key in ("selection_rate", "critical_exact_rate"):
                        self.assertLessEqual(rate(cell_a[key]), rate(cell_b[key]), (key, ctx))
                    ci_b, ci_a = cell_b["critical_exact_ci"], cell_a["critical_exact_ci"]
                    upper_b = math.inf if ci_b == INSUFFICIENT else ci_b[1]
                    upper_a = math.inf if ci_a == INSUFFICIENT else ci_a[1]
                    self.assertLessEqual(upper_a, upper_b, ctx)
                if a["routes"][s]["primary"] == c:
                    self.assertEqual(b["routes"][s]["primary"], c, (s, ctx))
            sb, sa = b["summary"][c], a["summary"][c]
            for key in ("macro_critical_exact_rate", "worst_stratum_critical_exact_rate"):
                self.assertLessEqual(rate(sa[key]), rate(sb[key]) + 1e-12, (key, ctx))
            self.assertLessEqual(set(sa["strata_insufficient"]), set(sb["strata_insufficient"]))

    def test_pairing_counts_discordant_docs(self) -> None:
        recs = docs("s", "inc", exact=1) + docs("s", "c", exact=2)
        p = build_report(recs, incumbent="inc")["strata"]["s"]["paired_vs_incumbent"]["c"]
        self.assertEqual((p["candidate_only_exact"], p["incumbent_only_exact"]), (5, 0))


if __name__ == "__main__":
    unittest.main()
