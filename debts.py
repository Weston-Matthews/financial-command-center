"""Debt inventory and payoff-plan simulator."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

STRATEGIES = {
    "avalanche": {
        "label": "Avalanche — highest interest first",
        "blurb": "Puts extra cash on the costliest APR. Usually the least interest paid.",
    },
    "snowball": {
        "label": "Snowball — lowest balance first",
        "blurb": "Clears the smallest balance first for quick wins, then rolls that payment forward.",
    },
    "highest_balance": {
        "label": "Highest balance first",
        "blurb": "Attacks the largest principal first. Slower wins; use only if that debt is stressing you most.",
    },
    "lowest_apr": {
        "label": "Lowest interest first",
        "blurb": "Pays cheap debt first. Rarely optimal — included so you can compare.",
    },
}


def principal(account: dict) -> float:
    return abs(float(account.get("balance") or 0))


def debt_accounts(accounts: list[dict]) -> list[dict]:
    out = []
    for a in accounts:
        if a.get("type") not in {"credit", "loan"}:
            continue
        bal = float(a.get("balance") or 0)
        if bal >= 0 and principal(a) == 0:
            continue
        p = principal(a) if bal <= 0 else bal
        if p <= 0.005:
            continue
        minp = float(a.get("min_payment") or 0)
        if minp <= 0:
            minp = max(25.0, round(p * 0.02, 2))
        out.append(
            {
                "id": a["id"],
                "name": a["name"],
                "institution": a.get("institution") or "",
                "type": a["type"],
                "balance": -p if bal <= 0 else bal,
                "principal": round(p, 2),
                "apr": float(a.get("apr") or 0),
                "min_payment": round(minp, 2),
                "due_day": a.get("due_day"),
            }
        )
    return out


def sort_key(strategy: str, d: dict) -> tuple:
    s = (strategy or "avalanche").lower()
    if s in {"snowball", "lowest_balance"}:  # lowest_balance kept as alias of snowball
        return (d["principal"], -d["apr"], d["name"])
    if s == "highest_balance":
        return (-d["principal"], -d["apr"], d["name"])
    if s == "lowest_apr":
        return (d["apr"], d["principal"], d["name"])
    # avalanche default
    return (-d["apr"], d["principal"], d["name"])


def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    i = year * 12 + (month - 1) + n
    return i // 12, i % 12 + 1


def simulate(
    debts: list[dict],
    strategy: str = "avalanche",
    extra_monthly: float = 0.0,
    today: date | None = None,
    max_months: int = 360,
) -> dict[str, Any]:
    today = today or date.today()
    extra_monthly = max(0.0, float(extra_monthly or 0))
    working = [
        {
            "id": d["id"],
            "name": d["name"],
            "type": d["type"],
            "apr": d["apr"],
            "min_payment": d["min_payment"],
            "principal": d["principal"],
            "balance": d["principal"],
        }
        for d in debts
        if d["principal"] > 0
    ]
    if not working:
        return {
            "strategy": strategy,
            "strategy_meta": STRATEGIES.get(
                "snowball" if strategy == "lowest_balance" else strategy,
                STRATEGIES["avalanche"],
            ),
            "extra_monthly": extra_monthly,
            "order": [],
            "timeline": [],
            "totals": {
                "principal": 0,
                "min_payments": 0,
                "months": 0,
                "interest": 0,
                "paid": 0,
                "payoff_date": None,
            },
            "note": "No credit cards or loans with a remaining balance.",
        }

    order = sorted(working, key=lambda d: sort_key(strategy, d))
    paid_off: list[dict] = []
    interest_total = 0.0
    paid_total = 0.0
    months = 0
    freed = 0.0  # min payments from paid-off debts roll into extra (snowball effect)

    while months < max_months and any(d["balance"] > 0.005 for d in working):
        months += 1
        month_extra = extra_monthly + freed
        # Accrue interest first
        for d in working:
            if d["balance"] <= 0.005:
                continue
            monthly_rate = (d["apr"] / 100.0) / 12.0
            interest = round(d["balance"] * monthly_rate, 2)
            d["balance"] = round(d["balance"] + interest, 2)
            interest_total += interest

        # Minimums
        for d in working:
            if d["balance"] <= 0.005:
                continue
            pay = min(d["min_payment"], d["balance"])
            d["balance"] = round(d["balance"] - pay, 2)
            paid_total += pay
            if d["balance"] <= 0.005 and d["id"] not in {p["id"] for p in paid_off}:
                leftover_min = max(d["min_payment"] - pay, 0)
                month_extra += leftover_min
                y, m = add_months(today.year, today.month, months)
                last = monthrange(y, m)[1]
                paid_off.append(
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "month": months,
                        "payoff_date": date(y, m, last).isoformat(),
                    }
                )
                freed += d["min_payment"]
                d["balance"] = 0.0

        # Extra toward current target (first unpaid in strategy order)
        targets = [d for d in order if d["balance"] > 0.005]
        while month_extra > 0.005 and targets:
            target = targets[0]
            pay = min(month_extra, target["balance"])
            target["balance"] = round(target["balance"] - pay, 2)
            month_extra = round(month_extra - pay, 2)
            paid_total += pay
            if target["balance"] <= 0.005:
                y, m = add_months(today.year, today.month, months)
                last = monthrange(y, m)[1]
                if target["id"] not in {p["id"] for p in paid_off}:
                    paid_off.append(
                        {
                            "id": target["id"],
                            "name": target["name"],
                            "month": months,
                            "payoff_date": date(y, m, last).isoformat(),
                        }
                    )
                    freed += target["min_payment"]
                target["balance"] = 0.0
                targets = [d for d in order if d["balance"] > 0.005]

    y, m = add_months(today.year, today.month, months) if months else (today.year, today.month)
    payoff = date(y, m, monthrange(y, m)[1]).isoformat() if months else None
    remaining = round(sum(d["balance"] for d in working), 2)

    ranked = []
    for i, d in enumerate(order, start=1):
        hit = next((p for p in paid_off if p["id"] == d["id"]), None)
        ranked.append(
            {
                "rank": i,
                "id": d["id"],
                "name": d["name"],
                "type": d["type"],
                "apr": d["apr"],
                "principal": next(x["principal"] for x in debts if x["id"] == d["id"]),
                "min_payment": d["min_payment"],
                "months": hit["month"] if hit else (None if remaining > 0 else months),
                "payoff_date": hit["payoff_date"] if hit else None,
                "status": "paid in plan" if hit else ("still open" if d["balance"] > 0.005 else "paid in plan"),
            }
        )

    return {
        "strategy": strategy,
        "strategy_meta": STRATEGIES.get(
            "snowball" if strategy == "lowest_balance" else strategy,
            STRATEGIES["avalanche"],
        ),
        "extra_monthly": extra_monthly,
        "order": ranked,
        "timeline": paid_off,
        "totals": {
            "principal": round(sum(d["principal"] for d in debts), 2),
            "min_payments": round(sum(d["min_payment"] for d in debts), 2),
            "months": months,
            "interest": round(interest_total, 2),
            "paid": round(paid_total, 2),
            "remaining": remaining,
            "payoff_date": payoff if remaining <= 0.005 else None,
        },
        "note": (
            None
            if remaining <= 0.005
            else "Plan did not finish in 30 years at this payment level. Raise the extra payment or check minimums."
        ),
    }


def compare_strategies(debts: list[dict], extra_monthly: float, today: date | None = None) -> list[dict]:
    rows = []
    for key in ("avalanche", "snowball", "highest_balance", "lowest_apr"):
        plan = simulate(debts, key, extra_monthly, today)
        t = plan["totals"]
        rows.append(
            {
                "strategy": key,
                "label": STRATEGIES[key]["label"],
                "months": t["months"],
                "interest": t["interest"],
                "payoff_date": t["payoff_date"],
                "first_target": plan["order"][0]["name"] if plan["order"] else None,
            }
        )
    return rows
