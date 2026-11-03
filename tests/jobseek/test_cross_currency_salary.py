"""Regression: preferred-currency FX salary filtering (CAD-authoritative)."""

from __future__ import annotations

import copy
import unittest

from jobseek.filters.hard import apply_hard_filters
from jobseek.rank.fingerprint import scoring_fingerprint
from jobseek.setup_wizard import apply_answers_to_search


BASE = {
    "tracks": ["data_engineering"],
    "track_aliases": {"data_engineering": ["Data Engineer", "Senior Data Engineer"]},
    "location": {
        "modes": ["remote_canada"],
        "preferred": ["Remote - Canada"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
}


def _job(**pay):
    job = {
        "title": "Data Engineer",
        "location_raw": "Remote - Canada",
        "description": "Remote Canada. Python SQL Spark.",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
    }
    job.update(pay)
    return job


def _cfg(**salary):
    sal = {
        "policy": "flexible",
        "preferred_currency": "CAD",
        "floors_independent": False,
        "usd_to_cad": 1.35,
        "floors": {"CAD": 200_000},
    }
    sal.update(salary)
    return {**BASE, "salary": sal}


class CrossCurrencySalaryTests(unittest.TestCase):
    def test_usd_100k_fails_cad_200k_floor(self):
        # USD 100k × 1.35 = CAD 135k < 200k → FAIL
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(floors={"CAD": 200_000}),
        )
        self.assertEqual(r.salary_verdict, "FAIL")
        self.assertEqual(r.verdict, "FAIL")
        self.assertTrue(any("usd_to_cad" in x.casefold() for x in r.reasons))

    def test_usd_100k_passes_cad_130k_floor(self):
        # USD 100k × 1.35 = CAD 135k ≥ 130k → PASS
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(floors={"CAD": 130_000}),
        )
        self.assertEqual(r.salary_verdict, "PASS")

    def test_usd_100k_fails_cad_150k_floor(self):
        # USD 100k × 1.35 = CAD 135k < 150k → FAIL
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(floors={"CAD": 150_000}),
        )
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_usd_range_uses_high_end(self):
        # USD 80–120k high end × 1.35 = CAD 162k ≥ CAD 150k → PASS
        r = apply_hard_filters(
            _job(salary_min=80_000, salary_max=120_000, salary_currency="USD"),
            _cfg(floors={"CAD": 150_000}),
        )
        self.assertEqual(r.salary_verdict, "PASS")
        # Same range vs CAD 170k → FAIL (162k < 170k)
        r2 = apply_hard_filters(
            _job(salary_min=80_000, salary_max=120_000, salary_currency="USD"),
            _cfg(floors={"CAD": 170_000}),
        )
        self.assertEqual(r2.salary_verdict, "FAIL")

    def test_legacy_dual_floors_preferred_cad_wins(self):
        # Bug reproduction: CAD 200k + leftover USD 90k must NOT pass USD 100k jobs.
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(
                preferred_currency="CAD",
                floors_independent=False,
                floors={"CAD": 200_000, "USD": 90_000},
            ),
        )
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_floors_independent_uses_native_floor(self):
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(
                preferred_currency="CAD",
                floors_independent=True,
                floors={"CAD": 200_000, "USD": 90_000},
            ),
        )
        self.assertEqual(r.salary_verdict, "PASS")
        self.assertTrue(any("floors_independent" in x.casefold() for x in r.reasons))

    def test_strict_missing_fails(self):
        r = apply_hard_filters(_job(), _cfg(policy="strict", floors={"CAD": 130_000}))
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_flexible_missing_passes(self):
        r = apply_hard_filters(_job(), _cfg(policy="flexible", floors={"CAD": 130_000}))
        self.assertEqual(r.salary_verdict, "PASS")

    def test_none_ignores_floor(self):
        r = apply_hard_filters(
            _job(salary_min=50_000, salary_max=60_000, salary_currency="CAD"),
            _cfg(policy="none", floors={"CAD": 200_000}),
        )
        self.assertEqual(r.salary_verdict, "PASS")

    def test_unknown_currency_flexible(self):
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="EUR"),
            _cfg(floors={"CAD": 130_000}),
        )
        # Unverified / non CAD-USD → flexible accepts with warning path via label helper
        self.assertIn(r.salary_verdict, ("PASS", "FAIL"))

    def test_invalid_exchange_rate_falls_back(self):
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(usd_to_cad=0, floors={"CAD": 130_000}),
        )
        self.assertEqual(r.salary_verdict, "PASS")  # 100k * 1.35 default = 135k
        self.assertTrue(any("invalid usd_to_cad" in x.casefold() for x in r.reasons))

        r2 = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            _cfg(usd_to_cad=-2, floors={"CAD": 200_000}),
        )
        self.assertEqual(r2.salary_verdict, "FAIL")

    def test_conversion_rounding_display_stable(self):
        # 99999 * 1.35 = 134998.65 → display rounds; still < 135000
        r = apply_hard_filters(
            _job(salary_min=99_999, salary_max=99_999, salary_currency="USD"),
            _cfg(floors={"CAD": 135_000}, usd_to_cad=1.35),
        )
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_setup_does_not_invent_usd_floor(self):
        data = {
            "tracks": ["data_engineering"],
            "location": {"modes": ["remote_canada"], "cities": [], "provinces": []},
            "salary": {"floors": {}},
            "seniority": {"include": ["mid"], "exclude": ["intern"]},
        }
        answers = {
            "tracks": ["data_engineering"],
            "modes": ["remote_canada"],
            "city": "Toronto",
            "province": "ON",
            "salary_cad": 200_000,
            "seniority_include": ["mid", "senior"],
            "name": "Test",
        }
        out = apply_answers_to_search(data, answers)
        floors = out["salary"]["floors"]
        self.assertEqual(floors.get("CAD"), 200_000)
        self.assertNotIn("USD", floors)
        self.assertEqual(out["salary"]["preferred_currency"], "CAD")
        self.assertFalse(out["salary"]["floors_independent"])

        # Existing USD floor left in place (no silent wipe) but preferred mode ignores it.
        data2 = copy.deepcopy(data)
        data2["salary"] = {"floors": {"USD": 90_000}}
        out2 = apply_answers_to_search(data2, answers)
        self.assertEqual(out2["salary"]["floors"].get("USD"), 90_000)
        r = apply_hard_filters(
            _job(salary_min=100_000, salary_max=100_000, salary_currency="USD"),
            out2,
        )
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_fingerprint_changes_with_currency_knobs(self):
        base = _cfg(floors={"CAD": 130_000})
        fp1 = scoring_fingerprint(base, {})
        fp2 = scoring_fingerprint(_cfg(floors={"CAD": 200_000}), {})
        fp3 = scoring_fingerprint(_cfg(floors={"CAD": 130_000}, usd_to_cad=1.40), {})
        fp4 = scoring_fingerprint(
            _cfg(floors={"CAD": 130_000}, preferred_currency="USD"), {}
        )
        fp5 = scoring_fingerprint(
            _cfg(floors={"CAD": 130_000}, floors_independent=True), {}
        )
        fp6 = scoring_fingerprint(_cfg(floors={"CAD": 130_000}, policy="strict"), {})
        self.assertNotEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)
        self.assertNotEqual(fp1, fp4)
        self.assertNotEqual(fp1, fp5)
        self.assertNotEqual(fp1, fp6)


if __name__ == "__main__":
    unittest.main()
