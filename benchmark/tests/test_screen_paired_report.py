from __future__ import annotations

import copy
import math
import unittest
from typing import Any

from akc_absorption.metrics import _SplitMix64

from benchmark.screen.paired_report import INSUFFICIENT, build_report
from benchmark.w6.v2.grading import wilson_interval


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
        # c reads s0 perfectly and fails s1..s9; the failures keep the page's gold n.
        recs = [*docs("s", "inc", k=10, exact=1, n=2), rec("s", "c", "s0")]
        recs += [rec("s", "c", f"s{i}", exact=0, fail=f, cost=None) for i in range(1, 10)]
        recs += [rec("s", "dead", "s0", exact=0, fail=("contract_failed",), cost=None)]
        r = build_report(recs, incumbent="inc")
        self.assertEqual(r["routes"]["s"]["primary"], "inc")
        self.assertAlmostEqual(r["strata"]["s"]["cells"]["c"]["critical_exact_rate"], 0.1)
        self.assertNotIn("dead", r["routes"]["s"]["alternatives"])
        self.assertEqual(r["strata"]["s"]["rejected"]["dead"], "no_accepted_pages")
        # A failure that drops the page's gold n out of the denominator is refused.
        for i in range(1, 10):
            recs[10 + i]["critical"]["n"] = 0
        with self.assertRaises(ValueError):
            build_report(recs, incumbent="inc")

    def test_summary_worst_stratum_counts_failed_pages(self) -> None:
        f = ("provider_unavailable",)
        recs = docs("a", "c", k=10, exact=1)
        recs += [rec("b", "c", "ok")]
        recs += [rec("b", "c", f"f{i}", exact=0, fail=f, cost=None) for i in range(9)]
        c = build_report(recs, incumbent="inc")["summary"]["c"]
        self.assertEqual(c["worst_stratum"], "b")
        self.assertAlmostEqual(c["worst_stratum_critical_exact_rate"], 0.1)
        # Failures written with n=0 where another candidate records the gold n=2: refused.
        for r in recs[11:]:
            r["critical"]["n"] = 0
        recs += [rec("b", "inc", f"f{i}", exact=0) for i in range(9)]
        with self.assertRaises(ValueError):
            build_report(recs, incumbent="inc")

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
        key = "critical_exact_rate"
        before = build_report(recs, incumbent="c")["strata"]["s"]["cells"]["c"][key]
        recs[1]["hard_failures"] = ["provider_unavailable"]
        after = build_report(recs, incumbent="c")["strata"]["s"]["cells"]["c"][key]
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
        # Nine of ten pages failed, each keeping its gold n=10: 10 of 100 fields, 0.1.
        recs = [rec("s", "inc", f"d{i}", n=10, exact=9) for i in range(10)]
        recs += [rec("s", "c", "d0", n=10, exact=10)]
        recs += [rec("s", "c", f"d{i}", n=10, exact=0, fail=f) for i in range(1, 10)]
        rep = build_report(recs, incumbent="inc")
        cells = rep["strata"]["s"]["cells"]
        self.assertEqual((cells["c"]["critical_exact"], cells["c"]["critical_n"]), (10, 100))
        self.assertAlmostEqual(cells["c"]["critical_exact_rate"], 0.1)
        self.assertAlmostEqual(cells["inc"]["critical_exact_rate"], 0.9)
        self.assertEqual(rep["routes"]["s"]["primary"], "inc")
        # The same failures written with n=0 would leave the denominator: refused.
        for r in recs[11:]:
            r["critical"]["n"] = 0
        with self.assertRaises(ValueError):
            build_report(recs, incumbent="inc")
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
                for cell in st["cells"].values():
                    v = cell["critical_exact_rate"]
                    self.assertTrue(v == INSUFFICIENT or 0.0 <= v <= 1.0, (v, r))

    def test_property_failing_a_page_never_improves_its_candidate(self) -> None:
        """Fuzz: failing accepted pages or adding failed ones never improves the
        candidate's cell rate, either Wilson bound, macro, worst stratum or primary;
        and in every report the primary's reported rate is the highest eligible one
        and the summary repeats the cell's rate."""

        def rate(x: Any) -> float:
            return math.inf if x in (INSUFFICIENT, None) else float(x)

        def subset(items: list[str]) -> list[str]:
            mask = 1 + g.below(2 ** len(items) - 1)
            return [x for k, x in enumerate(items) if mask >> k & 1]

        g = _SplitMix64(20261116)
        for _ in range(400):
            recs: list[dict[str, Any]] = []
            gold: dict[tuple[str, int, int], int] = {}
            for s in subset(["a", "b", "c"]):
                for cand in subset(["inc", "c1", "c2"]):
                    for d in range(1 + g.below(3)):
                        for p in range(1 + g.below(3)):
                            # Gold critical n is a page property, shared by every candidate.
                            n = gold.setdefault((s, d, p), g.below(5))
                            r = rec(s, cand, f"{s}{d}", n=n, exact=g.below(n + 1))
                            r["page_id"] = f"{s}{d}-{p}"
                            r["metrics"]["cer"] = g.below(1000) / 1000
                            if g.below(10) < 3:
                                r["hard_failures"] = ["provider_unavailable"]
                            recs.append(r)
            # Any candidate's record (failed or not) disagreeing on a page's gold n is refused.
            keys = [(r["stratum"], r["doc_id"], r["page_id"]) for r in recs]
            shared = [i for i, k in enumerate(keys) if keys.count(k) > 1]
            if shared:
                bad = copy.deepcopy(recs)
                bad[shared[g.below(len(shared))]]["critical"]["n"] += 1 + g.below(3)
                with self.assertRaises(ValueError):
                    build_report(bad, incumbent="inc")
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
                    key = "critical_exact_rate"
                    self.assertLessEqual(rate(cell_a[key]), rate(cell_b[key]), (key, ctx))
                    # "insufficient" is the uninformative interval [0, 1].
                    ci_b, ci_a = (
                        [0.0, 1.0] if ci == INSUFFICIENT else ci
                        for ci in (cell_b["critical_exact_ci"], cell_a["critical_exact_ci"])
                    )
                    self.assertLessEqual(ci_a[0], ci_b[0], ctx)
                    self.assertLessEqual(ci_a[1], ci_b[1], ctx)
                if a["routes"][s]["primary"] == c:
                    self.assertEqual(b["routes"][s]["primary"], c, (s, ctx))
            sb, sa = b["summary"][c], a["summary"][c]
            for key in ("macro_critical_exact_rate", "worst_stratum_critical_exact_rate"):
                self.assertLessEqual(rate(sa[key]), rate(sb[key]) + 1e-12, (key, ctx))
            self.assertLessEqual(set(sa["strata_insufficient"]), set(sb["strata_insufficient"]))
            for rep in (b, a):
                self.assert_one_rate(rep, ctx)

    def assert_one_rate(self, rep: dict[str, Any], ctx: Any = None) -> None:
        """Selection, the cell, its CI and the summary all show the same rate."""
        for s, st in rep["strata"].items():
            cells, primary = st["cells"], rep["routes"][s]["primary"]
            eligible = [c for c in cells if c not in st["rejected"]]
            if primary is not None:
                top = max(cells[c]["critical_exact_rate"] for c in eligible)
                self.assertEqual(cells[primary]["critical_exact_rate"], top, (s, ctx))
            for cell in cells.values():
                if cell["critical_exact_rate"] == INSUFFICIENT:
                    self.assertEqual(cell["critical_exact_ci"], INSUFFICIENT, ctx)
                    continue
                # Field-pooled: integer exact fields over every gold critical field.
                self.assertIsInstance(cell["critical_exact"], int, ctx)
                self.assertLessEqual(cell["critical_exact"], cell["critical_n"], ctx)
                if cell["critical_n"] == 0:  # every page failed and none had critical fields
                    self.assertEqual(
                        (cell["critical_exact_rate"], cell["failures"]), (0.0, cell["pages"])
                    )
                else:
                    self.assertEqual(
                        cell["critical_exact_rate"], cell["critical_exact"] / cell["critical_n"]
                    )
                self.assertEqual(
                    cell["critical_exact_ci"],
                    wilson_interval(cell["critical_exact"], cell["critical_n"]),
                    ctx,
                )
        for c, summ in rep["summary"].items():
            rates = [
                st["cells"][c]["critical_exact_rate"]
                for st in rep["strata"].values()
                if c in st["cells"] and st["cells"][c]["critical_exact_rate"] != INSUFFICIENT
            ]
            if rates:
                self.assertEqual(summ["worst_stratum_critical_exact_rate"], min(rates), ctx)
                self.assertAlmostEqual(summ["macro_critical_exact_rate"], sum(rates) / len(rates))
                worst = rep["strata"][summ["worst_stratum"]]["cells"][c]["critical_exact_rate"]
                self.assertEqual(worst, summ["worst_stratum_critical_exact_rate"], ctx)

    def test_one_rate_for_selection_cell_and_summary(self) -> None:
        f = ("provider_unavailable",)
        # B1: c is 1/1 and 1/9 fields, inc 0/1 and 9/9. The rate is field-pooled
        # (c 2/10, inc 9/10), the primary is chosen on it, and the summary repeats it.
        recs = [rec("s", "c", "p1", n=1, exact=1), rec("s", "c", "p2", n=9, exact=1)]
        recs += [rec("s", "inc", "p1", n=1, exact=0), rec("s", "inc", "p2", n=9, exact=9)]
        rep = build_report(recs, incumbent="inc")
        cells = rep["strata"]["s"]["cells"]
        self.assertEqual(rep["routes"]["s"]["primary"], "inc")
        self.assertEqual((cells["c"]["critical_exact"], cells["c"]["critical_n"]), (2, 10))
        self.assertAlmostEqual(cells["c"]["critical_exact_rate"], 0.2)
        self.assertAlmostEqual(cells["inc"]["critical_exact_rate"], 0.9)
        self.assertEqual(cells["c"]["critical_exact_ci"], wilson_interval(2, 10))
        self.assertEqual(
            rep["summary"]["c"]["macro_critical_exact_rate"], cells["c"]["critical_exact_rate"]
        )
        self.assertNotIn("selection_rate", cells["c"])
        self.assert_one_rate(rep)
        # C1: one field right of 101 never beats 99 of 101, however the pages split.
        recs = [rec("s", "c", "p1", n=1, exact=1), rec("s", "c", "p2", n=100, exact=0)]
        recs += [rec("s", "inc", "p1", n=1, exact=0), rec("s", "inc", "p2", n=100, exact=99)]
        rep = build_report(recs, incumbent="inc")
        cells = rep["strata"]["s"]["cells"]
        self.assertEqual(rep["routes"]["s"]["primary"], "inc")
        self.assertAlmostEqual(cells["c"]["critical_exact_rate"], 1 / 101)
        self.assertAlmostEqual(cells["inc"]["critical_exact_rate"], 99 / 101)
        # B2: an all-failed cell is 0.0 over its gold critical field count.
        recs = [rec("s", "c", f"f{i}", n=5, exact=0, fail=f) for i in range(3)]
        cell = build_report(recs, incumbent="c")["strata"]["s"]["cells"]["c"]
        self.assertEqual(
            (cell["critical_n"], cell["critical_exact_rate"], cell["critical_exact_ci"]),
            (15, 0.0, wilson_interval(0, 15)),
        )
        # B3: a page number reused by another document does not lend it that page's n.
        big = [rec("s", "inc", "big", n=40, exact=40), rec("s", "c", "big", n=40, exact=40)]
        small = rec("s", "c", "small", n=1, exact=0, fail=f)
        for r in (*big, small):
            r["page_id"] = "p1"
        cell = build_report([*big, small], incumbent="inc")["strata"]["s"]["cells"]["c"]
        self.assertEqual((cell["critical_exact"], cell["critical_n"]), (40, 41))
        self.assertAlmostEqual(cell["critical_exact_rate"], 40 / 41)

    def test_duplicate_page_record_refused(self) -> None:
        recs = [rec("s", "c", "p1"), rec("s", "c", "p2", exact=0)]
        with self.assertRaises(ValueError):
            build_report([*recs, copy.deepcopy(recs[0])], incumbent="c")
        # The same page under another candidate or stratum is not a duplicate.
        build_report([*recs, rec("s", "inc", "p1"), rec("t", "c", "p1")], incumbent="c")

    def test_pairing_counts_discordant_docs(self) -> None:
        recs = docs("s", "inc", exact=1) + docs("s", "c", exact=2)
        p = build_report(recs, incumbent="inc")["strata"]["s"]["paired_vs_incumbent"]["c"]
        self.assertEqual((p["candidate_only_exact"], p["incumbent_only_exact"]), (5, 0))


if __name__ == "__main__":
    unittest.main()
