"""Product cost, capacity and projection calculations (all euro amounts)."""
from math import ceil


def product_cost(product):
    batch = max(1, float(product.get("batch_size", 1) or 1))
    ingredient_cost = sum(float(line.get("quantity", 0) or 0) * float(line.get("price", 0) or 0) for line in product.get("recipe", []))
    labour = float(product.get("labour_minutes", 0) or 0) / 60 * float(product.get("hourly_rate", 0) or 0)
    wastage_factor = 1 + max(0, float(product.get("wastage_pct", 0) or 0)) / 100
    ingredient_unit_cost = ingredient_cost / batch * wastage_factor
    labour_overhead_unit_cost = (labour / batch + float(product.get("overhead", 0) or 0)) * wastage_factor
    cost = ingredient_unit_cost + labour_overhead_unit_cost
    wholesale = float(product.get("wholesale", 0) or 0)
    retail = float(product.get("retail", 0) or 0)
    return {"unit_cost": cost, "ingredient_unit_cost": ingredient_unit_cost,
            "labour_overhead_unit_cost": labour_overhead_unit_cost, "batch_cost": cost * batch,
            "wholesale_margin": wholesale - cost, "retail_margin": retail - cost,
            "wholesale_margin_pct": (wholesale - cost) / wholesale * 100 if wholesale else 0,
            "retail_margin_pct": (retail - cost) / retail * 100 if retail else 0}


def suggested_price(unit_cost, target_margin_pct):
    margin = float(target_margin_pct) / 100
    if margin < 0 or margin >= 1:
        raise ValueError("Target margin must be between 0% and 100%.")
    return float(unit_cost) / (1 - margin)


def capacity(data):
    days = float(data.get("days", 0) or 0)
    hours = float(data.get("hours", 0) or 0)
    batch_size = max(1, float(data.get("batch_size", 1) or 1))
    batch_hours = float(data.get("batch_hours", 0) or 0) + float(data.get("setup_hours", 0) or 0)
    help_hours = float(data.get("help_hours", 0) or 0)
    weekly_hours = days * hours
    available = max(0, weekly_hours)
    units = int(available / batch_hours * batch_size) if batch_hours > 0 else 0
    alone_hours = max(0, weekly_hours - help_hours)
    limit = float(data.get("max_weekly_hours_alone", 40) or 40)
    return {"weekly_units": units, "monthly_units": round(units * 52 / 12), "weekly_hours": weekly_hours, "alone_hours": alone_hours, "over_40": help_hours == 0 and alone_hours > limit}


def project(data):
    """24-month cases; allowance is deliberately kept outside business cash flow."""
    product = data.get("product", {})
    cost = product_cost(product)["unit_cost"]
    fixed = float(data.get("fixed_cost", 0) or 0)
    units = float(data.get("units_month", 0) or 0)
    mix_wholesale = min(1, max(0, float(data.get("wholesale_mix", 60) or 0) / 100))
    revenue_per_unit = mix_wholesale * float(product.get("wholesale", 0) or 0) + (1 - mix_wholesale) * float(product.get("retail", 0) or 0)
    weekly_payment = float(data.get("weekly_payment", 0) or 0)
    drawings = float(data.get("drawings", 0) or 0)
    growth = float(data.get("growth_pct", 0) or 0) / 100
    sales_cut = min(100, max(0, float(data.get("sales_down_pct", 30) or 0))) / 100
    cost_increase = max(0, float(data.get("ingredient_up_pct", 10) or 0)) / 100
    rows = []
    for month in range(1, 25):
        ramp_units = units * ((1 + growth) ** ((month - 1) // 3))
        cases = {}
        for name, sales_factor, cost_factor in (("base", 1, 1), ("worse", 1 - sales_cut, 1 + cost_increase)):
            turnover = ramp_units * sales_factor * revenue_per_unit
            unit_cost = cost if name == "base" else product_cost(product)["ingredient_unit_cost"] * cost_factor + product_cost(product)["labour_overhead_unit_cost"]
            cogs = ramp_units * sales_factor * unit_cost
            net = turnover - cogs - fixed
            year_pct = float(data.get("year_1_pct", 100) if month <= 12 else data.get("year_2_pct", 75)) / 100
            allowance = weekly_payment * 52 / 12 * year_pct
            cases[name] = {"turnover": turnover, "cogs": cogs, "fixed": fixed, "net": net,
                           "allowance": allowance, "drawings": drawings,
                           "drawings_from_allowance": min(drawings, allowance),
                           "drawings_from_business": max(0, drawings - allowance)}
        rows.append({"month": month, **cases})
    return rows


def longest_negative_streak(rows, case="base"):
    best = current = 0
    for row in rows:
        current = current + 1 if row[case]["net"] < 0 else 0
        best = max(best, current)
    return best


def year_margin(rows, year, case="base"):
    part = rows[(year - 1) * 12:year * 12]
    turnover = sum(row[case]["turnover"] for row in part)
    net = sum(row[case]["net"] for row in part)
    return (net / turnover * 100) if turnover else 0


def break_even_month(rows, case="base"):
    return next((row["month"] for row in rows if row[case]["net"] >= 0), None)


def low_sales_months(rows, year=1, case="base"):
    part = rows[(year - 1) * 12:year * 12]
    average = sum(row[case]["turnover"] for row in part) / max(1, len(part))
    return sum(row[case]["turnover"] < average * 0.25 for row in part) if average else len(part)
