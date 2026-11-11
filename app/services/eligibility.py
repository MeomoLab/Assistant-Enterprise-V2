"""Indicative pre-check rules based on the supplied specification."""
from datetime import date, timedelta
from math import ceil

OTHER_PAYMENT_ADVICE = "The rules are different for each payment. Please read the official requirements for your own payment before you go further, and check with your Intreo adviser."


def paid_days(claim_start, today=None):
    today = today or date.today()
    elapsed = max(0, (today - claim_start).days)
    weeks, remainder = divmod(elapsed, 7)
    return weeks * 6 + min(remainder, 6)


def precheck(data, options, today=None, minimum_paid_days=234, paid_days_per_week=6):
    today = today or date.today()
    payment = next((p for p in options if p["id"] == data.get("payment_option")), None)
    if not payment:
        return {"result": "Unsure", "reason": "Choose the payment you receive and answer each quick check.", "paid_days": 0}
    rule = payment["rule"]
    if rule == "not_eligible":
        return {"result": "Not eligible", "reason": payment.get("note", "This payment is not on the BTWEA list."), "paid_days": 0}
    if rule == "unsure":
        result = {"result": "Unsure", "reason": payment.get("note", "This payment needs a discussion with Intreo."), "paid_days": 0}
        if payment["id"] in ("other_listed", "not_listed"):
            result["payment_advice"] = OTHER_PAYMENT_ADVICE
        return result
    try:
        start = date.fromisoformat(data.get("claim_start", ""))
    except ValueError:
        return {"result": "Unsure", "reason": "Add the start date of your continuous claim.", "paid_days": 0}
    days = paid_days(start, today)
    checks = data.get("checks", {})
    no_reasons = {
        "under_66": "You answered that you are not under 66.",
        "new_business": "The scheme is for a new business that is not yet operating.",
        "in_ireland": "The business needs to operate in Ireland.",
        "recent_claim": "A BTWEA or STEA claim in the last 5 years needs to be discussed with Intreo.",
    }
    for key, reason in no_reasons.items():
        if checks.get(key) == "no":
            return {"result": "Not eligible", "reason": reason, "paid_days": days}
    if days < minimum_paid_days:
        eligible_from = start + timedelta(weeks=ceil(minimum_paid_days / paid_days_per_week))
        return {"result": "Not eligible", "reason": f"Your estimate is {days} paid days. {minimum_paid_days} paid days are needed for this route. You could be eligible from {eligible_from:%-d %B %Y}.", "eligible_from": eligible_from.isoformat(), "paid_days": days}
    required = ("age_18", "under_66", "right_to_work", "employed", "new_business", "in_ireland", "recent_claim", "already_trading")
    if any(checks.get(key) not in ("yes", "no") for key in required):
        return {"result": "Unsure", "reason": "Answer each quick-check question to see an indicative result.", "paid_days": days}
    unsure = [key for key in ("age_18", "right_to_work") if checks.get(key) != "yes"]
    if checks.get("employed") != "no":
        unsure.append("employed")
    if checks.get("already_trading") != "no":
        unsure.append("already_trading")
    if unsure:
        return {"result": "Unsure", "reason": "One or more answers need a conversation with your Intreo adviser.", "paid_days": days}
    result = "Likely eligible, subject to extra conditions for your payment" if rule == "standard_with_note" else "Likely eligible"
    return {"result": result, "reason": payment.get("note", "Your answers match this first indicative route."), "paid_days": days, "payment_advice": OTHER_PAYMENT_ADVICE if payment["id"] in ("other_listed", "not_listed") else None}
