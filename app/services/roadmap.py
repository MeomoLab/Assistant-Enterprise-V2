"""Pure roadmap status calculations for the applicant home page."""


def roadmap_rows(steps, data, eligibility, risk_flags=None):
    required_checks = ("age_18", "under_66", "right_to_work", "employed", "new_business", "in_ireland", "recent_claim", "already_trading")
    check_answers = data.get("eligibility", {}).get("checks", {})
    market_answers = data.get("market", {}).get("self_employment", {})
    required_market = ("one_customer", "sets_prices", "sets_hours", "owns_equipment", "year_round")
    competitors = {item.get("name", "").strip().casefold() for item in data.get("market", {}).get("competitors", []) if item.get("name", "").strip()}
    pack = data.get("pack", {})
    decision = data.get("milestones", {}).get("decision", {})
    done = {
        "eligibility": bool(data.get("eligibility", {}).get("payment_option")) and bool(data.get("eligibility", {}).get("claim_start")) and all(check_answers.get(key) in ("yes", "no") for key in required_checks),
        "profile": all(data.get("profile", {}).get(key) for key in ("business_name", "idea", "customers", "where_trade", "background", "town", "county", "structure")),
        "intreo": bool(data.get("milestones", {}).get("intreo", {}).get("date")),
        "syob": bool(data.get("milestones", {}).get("syob", {}).get("date")),
        "market": len(competitors) >= 2 and bool(data.get("market", {}).get("difference")) and all(market_answers.get(key) in ("yes", "no") for key in required_market),
        "food": bool(data.get("food")) and all(data["food"].get(key) for key in ("hse", "haccp", "allergens", "claims", "insurance")),
        "numbers": bool(data.get("product", {}).get("name")) and bool(data.get("product", {}).get("recipe")) and bool(data.get("capacity", {}).get("days")) and bool(data.get("capacity", {}).get("hours")) and bool(data.get("projection", {}).get("units_month")),
        "risks": all(flag.get("id") in data.get("risk_acknowledged", []) for flag in (risk_flags or []) if flag.get("severity") == "Red"),
        "ldc": bool(data.get("milestones", {}).get("ldc", {}).get("date")),
        "pack": bool(data.get("milestones", {}).get("pack_sent", {}).get("date")) and all(pack.get(key) for key in ("btw2", "projection", "business_plan", "syob")),
        "decision": bool(decision.get("date")) and decision.get("outcome") in ("approved", "refused"),
        "trading": bool(data.get("milestones", {}).get("trading", {}).get("date")),
    }
    next_id = next((step["id"] for step in steps if not done.get(step["id"], False)), "trading")
    result = []
    for step in steps:
        status = "Done" if done.get(step["id"], False) else "Do now" if step["id"] == next_id else "Next"
        if step["id"] == "trading" and data.get("milestones", {}).get("decision", {}).get("outcome") != "approved":
            status = "Not yet"
        result.append({**step, "status": status})
    return result
