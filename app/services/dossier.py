"""Small derived summaries used by the print-friendly dossier."""
from .calculators import year_margin, break_even_month


def dossier_metrics(rows, cost, capacity):
    return {
        "year_1_margin": year_margin(rows, 1),
        "year_2_margin": year_margin(rows, 2),
        "break_even_month": break_even_month(rows),
        "month_24_net": rows[23]["base"]["net"],
        "unit_cost": cost["unit_cost"],
        "weekly_capacity": capacity["weekly_units"],
    }
