"""Local strategy coach — grounded in current numbers, no external API required."""

from __future__ import annotations

from typing import Any


def _money(n: float) -> str:
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


def brief(
    summary: dict,
    debts: list[dict],
    plan: dict,
    obligations: list[dict],
    allocation: dict | None = None,
) -> dict[str, Any]:
    from datetime import date as _date

    from engine import is_obligation_current

    today = _date.fromisoformat(summary["today"]) if summary.get("today") else _date.today()
    live = [o for o in obligations if is_obligation_current(o, today)]
    subs = [
        o
        for o in live
        if o.get("category") == "subscriptions" and o.get("direction") == "out"
    ]
    sub_total = round(sum(float(o["amount"]) for o in subs), 2)
    leftover = float((summary.get("budget") or {}).get("leftover") or 0)
    extra = float(plan.get("extra_monthly") or 0)
    alloc = allocation or {}
    runway = alloc.get("runway") or {}
    rw_months = runway.get("months")
    rw_target = float(runway.get("target") or 3)
    rw_status = runway.get("status") or "unknown"
    totals = plan.get("totals") or {}
    order = plan.get("order") or []
    first = order[0] if order else None

    cuts = []
    if sub_total > 0:
        cuts.append(
            {
                "title": "Subscriptions",
                "body": (
                    f"{_money(sub_total)}/month across {len(subs)} items "
                    f"({', '.join(o.get('vendor') or o['name'] for o in subs[:6])}"
                    f"{'…' if len(subs) > 6 else ''}). "
                    "Canceling one unused service is the cleanest extra payment."
                ),
            }
        )
    if rw_status in {"empty", "critical", "short"}:
        cuts.append(
            {
                "title": "Fund the floor first",
                "body": (
                    f"Savings cover {rw_months if rw_months is not None else 0:.1f} months of fixed bills "
                    f"(target {rw_target:.0f}). Short {_money(runway.get('gap_cash') or 0)}. "
                    "Extra debt and brokerage wait until the Safety job fills that gap — "
                    "unless a card is 15%+ APR, in which case split, don’t empty the fund."
                ),
            }
        )
    if leftover > 0 and extra < leftover * 0.15 and rw_status in {"ok", "strong"}:
        cuts.append(
            {
                "title": "Leftover vs extra debt",
                "body": (
                    f"Safe leftover is about {_money(leftover)} after bills and buffer, "
                    f"but extra debt payment is only {_money(extra)}. "
                    f"Even {_money(round(min(leftover * 0.2, leftover), 2))} more per month shortens the plan."
                ),
            }
        )
    dining = [o for o in live if o.get("category") in {"food", "other"} and o.get("direction") == "out"]
    if dining:
        cuts.append(
            {
                "title": "Flexible spend",
                "body": "Treat dining and 'other' as the first place to flex when a tight week shows up on the calendar.",
            }
        )
    if not cuts:
        cuts.append(
            {
                "title": "Keep the floor",
                "body": "No obvious subscription pile. Protect the buffer first; extra debt payments come from leftover, not from rent.",
            }
        )

    high_apr = [d for d in debts if d.get("apr", 0) >= 15]
    rec = "avalanche" if high_apr else "snowball"
    if high_apr:
        why = (
            f"{len(high_apr)} balance(s) at 15%+ APR. Avalanche usually saves the most interest "
            f"({_money(totals.get('interest') or 0)} estimated on the current plan)."
        )
    else:
        why = "APRs are relatively close. Snowball is fine if a quick win will help you stay consistent."

    if leftover < 0 or (summary.get("safe_to_spend") or 0) < 0:
        encourage = (
            "This month is tight. That is a cash-flow timing problem, not a character problem. "
            "Cover the next due dates first. Debt payoff can wait a cycle if checking would overdraft."
        )
    elif debts:
        encourage = (
            f"You already have the pieces: a bill calendar, minimums on the books, and a plan. "
            f"{'Focus extra on ' + first['name'] + '.' if first else ''} "
            "Small, boring extra payments beat an all-or-nothing reset."
        )
    else:
        encourage = "No revolving debt on the books. Protect the buffer and keep the calendar honest."

    paragraphs = [
        f"Cash {_money(summary.get('cash') or 0)} · investments {_money(summary.get('investments') or 0)} · "
        f"crypto {_money(summary.get('crypto') or 0)} · debt {_money(summary.get('debt') or 0)} · "
        f"net worth {_money(summary.get('net_worth') or 0)}.",
        f"Safe-to-spend this month {_money(summary.get('safe_to_spend') or 0)}; "
        f"next-30-days {_money(summary.get('next30_safe') or 0)} after a "
        f"{_money(summary.get('buffer') or 0)} buffer.",
        (
            f"Emergency fund {rw_months:.1f} months of fixed bills "
            f"(target {rw_target:.0f}) — {runway.get('headline') or ''}."
            if rw_months is not None
            else "Emergency fund runway unknown until recurring bills are on the books."
        ),
        why,
        encourage,
    ]

    return {
        "recommended_strategy": rec,
        "why": why,
        "encouragement": encourage,
        "cuts": cuts,
        "overview": paragraphs,
        "focus": first["name"] if first else None,
        "plan_months": totals.get("months"),
        "plan_interest": totals.get("interest"),
        "runway_months": rw_months,
        "runway_target": rw_target,
        "runway_status": rw_status,
        "runway_line": (
            f"Emergency fund {rw_months:.1f} months of fixed bills (target {rw_target:.0f}). "
            + (runway.get("headline") or "")
            if rw_months is not None
            else "Add recurring bills to measure emergency-fund runway."
        ),
    }


def answer(question: str, brief_data: dict, summary: dict, debts: list[dict], plan: dict) -> str:
    q = (question or "").strip().lower()
    totals = plan.get("totals") or {}
    extra = plan.get("extra_monthly") or 0
    first = (plan.get("order") or [None])[0]

    if not q:
        return "Ask anything about payoff order, cutting spend, or whether this month is safe."

    if any(w in q for w in ("snowball", "avalanche", "which debt", "what first", "strategy")):
        return (
            f"On the current extra of ${extra:,.2f}/mo, {plan.get('strategy_meta', {}).get('label', plan.get('strategy'))} "
            f"targets {first['name'] if first else 'nothing'} first. "
            f"{brief_data.get('why', '')} "
            f"Estimated interest { _money(totals.get('interest') or 0) } over "
            f"{totals.get('months') or '—'} months."
        )
    if any(w in q for w in ("cut", "spend", "subscription", "save more", "where")):
        bits = " ".join(c["body"] for c in brief_data.get("cuts") or [])
        return bits or "No obvious cuts jumped out. Use the calendar tight weeks as the signal."
    if any(w in q for w in ("ok", "safe", "overdraft", "this month", "stress", "anxious", "worried", "scared")):
        return brief_data.get("encouragement") + (
            f" Projected checking low is in Command. Safe-to-spend is "
            f"{_money(summary.get('safe_to_spend') or 0)} this month."
        )
    if any(w in q for w in ("emergency", "runway", "months of", "safety fund", "rainy")):
        return brief_data.get("runway_line") or "Open Command for months of fixed bills covered by savings."
    if any(w in q for w in ("invest", "brokerage", "401", "stock")):
        high = [d for d in debts if d.get("apr", 0) >= 10]
        if high:
            return (
                "If a card is running double-digit APR, extra payment there is a guaranteed return "
                "that beats most after-tax brokerage contributions this month. "
                "Keep any employer match; then dump extra at the high-APR balance."
            )
        return "APRs look moderate. Split leftover between the debt plan and regular investing — don't starve the buffer."
    if any(w in q for w in ("encourage", "motivation", "hard", "tired")):
        return brief_data.get("encouragement")
    return (
        brief_data.get("encouragement")
        + " If you want a specific comparison, ask “avalanche or snowball?” or “what can I cut?”"
    )
