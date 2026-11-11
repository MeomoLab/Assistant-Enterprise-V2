"""Indicative risk flags and practical fixes for the preparation workspace."""
from .calculators import longest_negative_streak, low_sales_months, year_margin


def build_flags(data, eligibility, capacity, rows, guidance):
    flags = []

    def add(severity, title, why, fix):
        stable_id = "".join(character.lower() if character.isalnum() else "-" for character in title).strip("-")
        flags.append({"id": stable_id, "severity": severity, "title": title, "why": why, "fix": fix})

    if data.get("eligibility", {}).get("checks", {}).get("already_trading") == "yes":
        add("Red", "Already started trading", "The scheme is for a new business that is not yet operating.", "Contact your Intreo Employment Personal Adviser or LDC before continuing.")
    if eligibility["result"] in ("Not eligible", "Unsure"):
        add("Amber", "Eligibility needs a conversation", eligibility["reason"], "Take your answers to your Intreo Employment Personal Adviser.")
    competitors = data.get("market", {}).get("competitors", [])
    distinct = {item.get("name", "").strip().casefold() for item in competitors if item.get("name", "").strip()}
    if len(distinct) < guidance["min_distinct_local_competitors"]:
        add("Red", "Add two local competitors", "The LDC guidance asks for a market view.", "Add distinct competitors and their public prices to your market research.")
    if not data.get("market", {}).get("difference", "").strip():
        add("Red", "Describe what makes your offer different", "The business case should explain its place in the market.", "Write a short comparison in your market research.")
    if capacity["over_40"]:
        add("Red", "Weekly production is over 40 hours alone", "This is above the LDC guidance threshold.", "Review the weekly plan or whether paid help is realistic.")
    threshold = guidance["min_net_margin_pct"]
    if data.get("product", {}).get("name") and year_margin(rows, 2) <= threshold:
        add("Red", f"Year 2 margin is at or below {threshold}%", "This threshold is LDC guidance, not a DSP rule.", "Review your costs, product mix and customer prices using evidence.")
    if data.get("product", {}).get("name") and year_margin(rows, 1) <= threshold < year_margin(rows, 2):
        add("Amber", f"Year 1 margin is at or below {threshold}%", "This threshold is LDC guidance.", "Review your costs, product mix and customer prices using evidence.")
    if rows[23]["base"]["net"] < float(data.get("projection", {}).get("drawings", 0) or 0):
        add("Red", "Month 24 cash flow cannot cover drawings", "The longer-term check excludes allowance.", "Review drawings and your business model's longer-term viability.")
    if data.get("projection", {}).get("units_month", 0) and data["projection"]["units_month"] > capacity["monthly_units"]:
        add("Amber", "Planned sales are above capacity", "The first month exceeds estimated maximum output.", "Review the weekly production plan and batch-time assumptions.")
    if longest_negative_streak(rows) > guidance["max_consecutive_negative_cash_months"]:
        add("Red", "More than three negative months in a row", "The base case has a sustained cash gap.", "Review the sales ramp and operating costs.")
    if longest_negative_streak(rows, "worse") > guidance["max_consecutive_negative_cash_months"]:
        add("Amber", "Worse-case cash gap lasts more than three months", "A slower sales case helps show what could go wrong.", "Consider what costs or savings could bridge this period.")
    if low_sales_months(rows, 1) >= 3 or low_sales_months(rows, 2) >= 3:
        add("Red", "Several low-sales months in a year", "The model shows sales below 25% of the year's average in three or more months.", "Revisit seasonality, customer diversity and year-round demand evidence.")
    self_employment = data.get("market", {}).get("self_employment", {})
    if self_employment.get("one_customer") == "yes":
        add("Red", "Most sales may come from one customer or former employer", "The guidelines expect a sufficiently large and diverse customer base.", "Build a broader customer plan and discuss the arrangement with your LDC.")
    if self_employment.get("year_round") == "no":
        add("Red", "Income may be seasonal", "Seasonal, temporary or part-time self-employment is not accepted under the scheme guidance.", "Show how demand and income can continue through the year, and discuss the plan with your LDC.")
    worrying = [key for key in ("sets_prices", "sets_hours", "owns_equipment") if self_employment.get(key) == "no"]
    if worrying:
        add("Amber", "Review your self-employment answers", "One or more answers may need more context.", "Discuss how you will control your work and earn through the year.")
    food = data.get("food", {})
    if not food.get("haccp"):
        add("Amber", "Food safety plan not marked ready", "A food-safety plan is part of preparation.", "Draft and review a HACCP plan with an appropriate adviser.")
    if not food.get("allergens"):
        add("Amber", "Allergen information not marked ready", "Food businesses need to understand allergen information and labelling.", "Review the 14 allergen rules for your products.")
    if not food.get("hse"):
        add("Amber", "HSE notification not marked ready", "Check the process and timing with an appropriate adviser.", "Use the HSE helper to prepare questions before submitting anything.")
    if not data.get("milestones", {}).get("syob", {}).get("date"):
        add("Amber", "SYOB course not recorded", "The application pack asks for confirmation of course completion.", "Record your course completion date when complete.")
    if not all(data.get("pack", {}).get(key) for key in ("btw2", "projection", "business_plan", "syob")):
        add("Amber", "Application pack checklist is incomplete", "The LDC recommendation pack includes multiple items.", "Work through the pack checklist with your Enterprise Officer.")
    if not data.get("profile", {}).get("business_name"):
        add("Green / info", "Profile is not complete", "Profile details appear in the business plan and dossier.", "Add the basic business details.")
    return flags
