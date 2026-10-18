"""Consistency checks on playbook findings (no database)."""

from orderintel.playbooks.checks import inconsistencies

OK_LATE = {
    "playbook": "late_delivery_diagnosis",
    "verdict": "elevated",
    "delivered_orders": 7003,
    "late_orders": 1328,
    "late_rate": 19.0,
    "baseline_rate": 5.8,
    "sellers_with_late_orders": 466,
    "top5_seller_share": 11.5,
    "top_states": [{"name": "RJ", "n": 864}],
    "review_n_late": 1296,
    "review_n_on_time": 5652,
    "one_star_share_late": 59.3,
}


def test_consistent_findings_pass():
    assert inconsistencies(OK_LATE) == []


def test_the_september_2016_contradiction_is_caught():
    """What the investigation reported before the window fix."""
    old = {
        **OK_LATE,
        "verdict": "insufficient_data",
        "delivered_orders": 0,
        "late_orders": 0,
        "late_rate": None,
        "sellers_with_late_orders": 1,
        "top_states": [],
        "review_n_late": 0,
        "review_n_on_time": 0,
    }
    problems = inconsistencies(old)
    assert any("but 0 late orders" in p for p in problems)


def test_impossible_counts_and_percentages_are_caught():
    bad = {
        **OK_LATE,
        "late_orders": 8000,
        "late_rate": 114.2,
        "top_states": [{"name": "SP", "n": 9000}],
        "review_n_on_time": 9000,
    }
    problems = " | ".join(inconsistencies(bad))
    for expected in ("exceed delivered", "late_rate is 114.2", "top_states SP", "reviewed orders"):
        assert expected in problems


def test_verdict_without_data_is_caught():
    assert inconsistencies(
        {
            **OK_LATE,
            "delivered_orders": 0,
            "late_orders": 0,
            "sellers_with_late_orders": 0,
            "top_states": [],
            "review_n_late": 0,
            "review_n_on_time": 0,
        }
    )
    assert inconsistencies(
        {
            "playbook": "low_review_diagnosis",
            "verdict": "elevated",
            "reviews": 0,
            "worst_sellers": [],
        }
    )


def test_review_groups_cannot_exceed_the_period():
    f = {
        "playbook": "low_review_diagnosis",
        "verdict": "nothing_notable",
        "reviews": 50,
        "one_star_share": 10.0,
        "one_star_from": {"late": 120.0},
        "worst_sellers": [{"name": "s1", "n": 70}],
    }
    problems = " | ".join(inconsistencies(f))
    assert "one_star_from[late]" in problems and "worst_sellers s1" in problems
