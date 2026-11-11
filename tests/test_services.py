from datetime import date, timedelta
import pytest

from app.services.calculators import capacity, product_cost, project, suggested_price
from app.services.eligibility import paid_days, precheck


def demo_product():
    return {
        "batch_size": 100,
        "wastage_pct": 0,
        "labour_minutes": 60,
        "hourly_rate": 15,
        "overhead": 0.20,
        "wholesale": 1.50,
        "retail": 2.80,
        "recipe": [
            {"name": "oats", "price": 3.50, "quantity": 2.5},
            {"name": "cacao", "price": 14, "quantity": 0.8},
            {"name": "agave", "price": 6, "quantity": 1.5},
            {"name": "wrappers", "price": 0.20, "quantity": 100},
        ],
    }


def eligible_answers():
    return {
        "payment_option": "ja",
        "claim_start": (date(2026, 11, 11) - timedelta(days=274)).isoformat(),
        "checks": {
            "age_18": "yes", "under_66": "yes", "right_to_work": "yes", "employed": "no",
            "new_business": "yes", "in_ireland": "yes", "recent_claim": "no", "already_trading": "no",
        },
    }


OPTIONS = [
    {"id": "ja", "rule": "standard"},
    {"id": "casual", "rule": "unsure"},
    {"id": "jb_jprb", "rule": "not_eligible", "note": "STEA"},
    {"id": "other_listed", "rule": "standard_with_note", "note": "extra conditions"},
    {"id": "not_listed", "rule": "unsure"},
]


def test_seeded_product_cost_matches_hand_calculation():
    result = product_cost(demo_product())
    # Ingredients €48.95 + labour €15 + overhead €20 = €83.95 per 100 units.
    assert result["batch_cost"] == pytest.approx(83.95)
    assert result["unit_cost"] == pytest.approx(0.8395)
    assert result["wholesale_margin"] == pytest.approx(0.6605)
    assert result["retail_margin"] == pytest.approx(1.9605)
    assert round(suggested_price(result["unit_cost"], 20), 2) == 1.05


def test_capacity_includes_batch_and_setup_time():
    result = capacity({"days": 4, "hours": 4, "batch_size": 100, "batch_hours": 3.5, "setup_hours": 0.5, "help_hours": 0})
    assert result["weekly_units"] == 400
    assert result["weekly_hours"] == 16
    assert result["over_40"] is False


def test_paid_day_edges_and_precheck_result():
    today = date(2026, 11, 11)
    assert paid_days(today - timedelta(days=271), today) == 233
    assert paid_days(today - timedelta(days=272), today) == 234
    assert paid_days(today - timedelta(days=274), today) == 235
    data = eligible_answers()
    data["claim_start"] = (today - timedelta(days=271)).isoformat()
    assert precheck(data, OPTIONS, today)["result"] == "Not eligible"
    data["claim_start"] = (today - timedelta(days=272)).isoformat()
    assert precheck(data, OPTIONS, today)["result"] == "Likely eligible"


def test_payment_options_keep_their_indicative_routes():
    data = eligible_answers()
    data["claim_start"] = (date(2026, 11, 11) - timedelta(days=300)).isoformat()
    assert precheck({**data, "payment_option": "casual"}, OPTIONS, date(2026, 11, 11))["result"] == "Unsure"
    assert precheck({**data, "payment_option": "jb_jprb"}, OPTIONS, date(2026, 11, 11))["result"] == "Not eligible"
    assert "extra conditions" in precheck({**data, "payment_option": "other_listed"}, OPTIONS, date(2026, 11, 11))["result"]


def test_allowance_is_separate_from_business_block():
    inputs = {"product": demo_product(), "fixed_cost": 950, "units_month": 1600, "wholesale_mix": 60, "weekly_payment": 250, "drawings": 900, "growth_pct": 3}
    first = project(inputs)
    second = project({**inputs, "weekly_payment": 400})
    assert first[0]["base"]["allowance"] == 250 * 52 / 12
    assert first[12]["base"]["allowance"] == 250 * 52 / 12 * 0.75
    assert first[23]["base"]["turnover"] == second[23]["base"]["turnover"]
    assert first[23]["base"]["net"] == second[23]["base"]["net"]
    assert first[23]["base"]["allowance"] != second[23]["base"]["allowance"]
