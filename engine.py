"""Cash-flow calendar, leftover budget, and rule-based advice."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def clamp_day(year: int, month: int, day: int) -> date:
    last = monthrange(year, month)[1]
    return date(year, month, min(max(day, 1), last))


def previous_weekday(d: date) -> date:
    """If d is Saturday or Sunday, walk back to the prior Friday."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def last_weekday_of_month(year: int, month: int) -> date:
    last = date(year, month, monthrange(year, month)[1])
    return previous_weekday(last)


def resolve_month_day(year: int, month: int, day_code: int, business_days: bool) -> date:
    """day_code: 1-31 fixed day, or -1 for last weekday of the month."""
    if int(day_code) == -1:
        d = last_weekday_of_month(year, month)
    else:
        d = clamp_day(year, month, int(day_code))
        if business_days:
            d = previous_weekday(d)
    return d


def obligation_end_date(ob: dict) -> date | None:
    """Last inclusive date this obligation may generate a hit. None = open-ended."""
    raw = ob.get("end_date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None
    return None


def is_obligation_current(ob: dict, as_of: date | None = None) -> bool:
    """True if the bill still applies on as_of (for coach / leftover logic)."""
    as_of = as_of or date.today()
    if not ob.get("active", 1):
        ed = obligation_end_date(ob)
        return bool(ed and ed >= as_of)
    ed = obligation_end_date(ob)
    if ed is not None and ed < as_of:
        return False
    return True


def occurrences_for(ob: dict, start: date, end: date) -> list[date]:
    """Generate occurrence dates in [start, end], respecting end_date and active.

    - end_date: last inclusive charge/income date (history kept up to that day)
    - active=0 without end_date: fully off (no occurrences)
    - active=0 with end_date: still emits dates on/before end_date so mid-month
      cancellations leave earlier hits in the calendar
    """
    cadence = (ob.get("cadence") or "monthly").lower()
    out: list[date] = []
    hard_end = obligation_end_date(ob)
    if not ob.get("active", 1) and hard_end is None:
        return []
    if hard_end is not None:
        if hard_end < start:
            return []
        end = min(end, hard_end)

    if cadence == "once":
        raw = ob.get("next_date")
        if raw:
            d = date.fromisoformat(raw)
            if start <= d <= end:
                out.append(d)
        return out

    if cadence == "monthly":
        due = int(ob.get("due_day") or 1)
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            d = clamp_day(cursor.year, cursor.month, due)
            if start <= d <= end:
                out.append(d)
            cursor = add_months(cursor, 1)
        return out

    if cadence == "yearly":
        raw = ob.get("next_date")
        due = int(ob.get("due_day") or 1)
        if raw:
            anchor = date.fromisoformat(raw)
            d = date(start.year, anchor.month, min(anchor.day, monthrange(start.year, anchor.month)[1]))
            if d < start:
                d = date(start.year + 1, anchor.month, min(anchor.day, monthrange(start.year + 1, anchor.month)[1]))
            if start <= d <= end:
                out.append(d)
        else:
            d = clamp_day(start.year, start.month, due)
            if start <= d <= end:
                out.append(d)
        return out

    if cadence in ("weekly", "biweekly"):
        weekday = ob.get("weekday")
        raw = ob.get("next_date")
        if raw:
            cursor = date.fromisoformat(raw)
        elif weekday is not None:
            cursor = start
            while cursor.weekday() != int(weekday):
                cursor += timedelta(days=1)
        else:
            return out
        step = 7 if cadence == "weekly" else 14
        while cursor < start:
            cursor += timedelta(days=step)
        while cursor <= end:
            out.append(cursor)
            cursor += timedelta(days=step)
        return out

    if cadence == "semimonthly":
        # Two pay rules per month.
        # due_day: 1-31 (fixed calendar day)
        # due_day_2: 1-31, or -1 for last weekday of the month
        # Weekend landing days roll back to the prior Friday (business-day schedule).
        first = int(ob.get("due_day") or 15)
        if ob.get("due_day_2") is not None and ob.get("due_day_2") != "":
            second = int(ob["due_day_2"])
        else:
            # Default pair: 15th + last weekday of month (common payroll pattern).
            second = -1 if first == 15 else (15 if first < 15 else -1)
        business = True
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            for day_code in (first, second):
                d = resolve_month_day(cursor.year, cursor.month, day_code, business)
                if start <= d <= end:
                    out.append(d)
            cursor = add_months(cursor, 1)
        return sorted(set(out))

    return out


def signed_amount(ob: dict) -> float:
    amt = float(ob["amount"])
    return amt if ob.get("direction") == "in" else -amt


def build_events(
    accounts: list[dict],
    obligations: list[dict],
    payments: list[dict],
    start: date,
    end: date,
) -> list[dict]:
    paid = {(p["obligation_id"], p["occur_date"]) for p in payments if p.get("paid")}
    by_id = {a["id"]: a for a in accounts}
    events: list[dict] = []

    for ob in obligations:
        for d in occurrences_for(ob, start, end):
            key = (ob["id"], d.isoformat())
            acct = by_id.get(ob["account_id"], {})
            dest = by_id.get(ob.get("dest_account_id")) if ob.get("dest_account_id") else None
            events.append(
                {
                    "obligation_id": ob["id"],
                    "name": ob["name"],
                    "vendor": ob.get("vendor") or ob["name"],
                    "date": d.isoformat(),
                    "amount": float(ob["amount"]),
                    "signed": signed_amount(ob),
                    "direction": ob.get("direction") or "out",
                    "account_id": ob["account_id"],
                    "account_name": acct.get("name", ""),
                    "dest_account_id": ob.get("dest_account_id"),
                    "dest_account_name": dest["name"] if dest else "",
                    "category": ob.get("category") or "",
                    "cadence": ob.get("cadence") or "",
                    "paid": key in paid,
                }
            )

    events.sort(key=lambda e: (e["date"], e["direction"] != "in", e["name"]))
    return events


def project_balances(
    accounts: list[dict],
    events: list[dict],
    today: date,
) -> dict[int, list[dict]]:
    """Per-account daily running projected balance from today through last event."""
    if not events:
        return {
            a["id"]: [
                {
                    "date": today.isoformat(),
                    "balance": float(a["balance"]),
                    "delta": 0.0,
                    "events": [],
                }
            ]
            for a in accounts
        }

    last = date.fromisoformat(max(e["date"] for e in events))
    start = today
    by_day: dict[str, list[dict]] = {}
    for e in events:
        if date.fromisoformat(e["date"]) < start:
            continue
        if e.get("paid"):
            continue
        by_day.setdefault(e["date"], []).append(e)

    running = {a["id"]: float(a["balance"]) for a in accounts}
    series: dict[int, list[dict]] = {a["id"]: [] for a in accounts}

    d = start
    while d <= last:
        iso = d.isoformat()
        day_events = by_day.get(iso, [])
        deltas = {aid: 0.0 for aid in running}
        for e in day_events:
            deltas[e["account_id"]] = deltas.get(e["account_id"], 0.0) + e["signed"]
            dest = e.get("dest_account_id")
            if dest:
                # Transfer: destination receives the outflow amount.
                deltas[dest] = deltas.get(dest, 0.0) + abs(e["signed"])
        for aid in running:
            running[aid] += deltas.get(aid, 0.0)
            series[aid].append(
                {
                    "date": iso,
                    "balance": round(running[aid], 2),
                    "delta": round(deltas.get(aid, 0.0), 2),
                    "events": [ev for ev in day_events if ev["account_id"] == aid or ev.get("dest_account_id") == aid],
                }
            )
        d += timedelta(days=1)
    return series


def month_window(today: date) -> tuple[date, date]:
    start = date(today.year, today.month, 1)
    end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    return start, end


def summarize(
    accounts: list[dict],
    obligations: list[dict],
    events: list[dict],
    series: dict[int, list[dict]],
    today: date,
    buffer: float,
) -> dict[str, Any]:
    cash_types = {"checking", "savings"}
    invest_types = {"brokerage"}
    crypto_types = {"crypto"}
    debt_types = {"credit", "loan"}

    def total(types: set[str]) -> float:
        return round(sum(float(a["balance"]) for a in accounts if a["type"] in types), 2)

    cash = total(cash_types)
    investments = total(invest_types)
    crypto = total(crypto_types)
    debt = total(debt_types)
    net_worth = round(sum(float(a["balance"]) for a in accounts), 2)

    month_start, month_end = month_window(today)
    month_events = [e for e in events if month_start.isoformat() <= e["date"] <= month_end.isoformat()]
    remaining = [e for e in month_events if not e["paid"] and date.fromisoformat(e["date"]) >= today]
    already = [e for e in month_events if e["paid"] or date.fromisoformat(e["date"]) < today]

    def vendor_flow(items: list[dict], direction: str) -> float:
        return round(
            sum(
                e["amount"]
                for e in items
                if e["direction"] == direction and e.get("category") != "savings"
            ),
            2,
        )

    checking = [a for a in accounts if a["type"] == "checking"]
    primary = checking[0] if checking else (accounts[0] if accounts else None)
    pid = primary["id"] if primary else None

    def from_primary(items: list[dict], direction: str) -> float:
        total = 0.0
        for e in items:
            if direction == "out" and e["direction"] == "out" and e["account_id"] == pid:
                total += e["amount"]
            if direction == "in" and e["direction"] == "in" and e["account_id"] == pid:
                total += e["amount"]
            if direction == "in" and e.get("dest_account_id") == pid:
                total += e["amount"]
        return round(total, 2)

    remaining_out = from_primary(remaining, "out")
    remaining_in = from_primary(remaining, "in")
    month_out = vendor_flow(month_events, "out")
    month_in = vendor_flow(month_events, "in")
    horizon = today + timedelta(days=30)
    next30 = [
        e
        for e in events
        if not e["paid"] and today.isoformat() <= e["date"] <= horizon.isoformat()
    ]
    next30_out = from_primary(next30, "out")
    next30_in = from_primary(next30, "in")

    lows = []
    for a in accounts:
        pts = series.get(a["id"]) or []
        if not pts:
            continue
        low = min(pts, key=lambda p: p["balance"])
        lows.append(
            {
                "account_id": a["id"],
                "account_name": a["name"],
                "type": a["type"],
                "current": round(float(a["balance"]), 2),
                "low_balance": low["balance"],
                "low_date": low["date"],
            }
        )

    primary_low = None
    if primary:
        primary_low = next((l for l in lows if l["account_id"] == primary["id"]), None)

    available = 0.0
    next30_safe = 0.0
    if primary:
        available = round(float(primary["balance"]) + remaining_in - remaining_out - buffer, 2)
        next30_safe = round(float(primary["balance"]) + next30_in - next30_out - buffer, 2)

    leftover = max(min(available, next30_safe), 0.0)
    budget = allocate_budget(leftover, obligations, max(remaining_out, next30_out))

    return {
        "today": today.isoformat(),
        "month": today.strftime("%Y-%m"),
        "cash": cash,
        "investments": investments,
        "crypto": crypto,
        "debt": debt,
        "net_worth": net_worth,
        "month_in": month_in,
        "month_out": month_out,
        "remaining_in": remaining_in,
        "remaining_out": remaining_out,
        "next30_in": next30_in,
        "next30_out": next30_out,
        "next30_safe": round(float(primary["balance"]) + next30_in - next30_out - buffer, 2) if primary else 0,
        "already_out": vendor_flow(already, "out"),
        "buffer": buffer,
        "safe_to_spend": available,
        "primary_account": primary,
        "primary_low": primary_low,
        "account_lows": lows,
        "budget": budget,
        "advice": advice(accounts, obligations, month_events, remaining, lows, available, buffer, today),
    }


def allocate_budget(leftover: float, obligations: list[dict], remaining_out: float) -> dict:
    """Split leftover after committed bills into a realistic month plan."""
    if leftover <= 0:
        return {
            "leftover": 0,
            "note": "No discretionary leftover after committed bills and buffer.",
            "buckets": [
                {"name": "Must-pay extras (food, gas, household)", "amount": 0, "pct": 0},
                {"name": "Extra debt payments", "amount": 0, "pct": 0},
                {"name": "Savings / investing", "amount": 0, "pct": 0},
                {"name": "Discretionary", "amount": 0, "pct": 0},
            ],
        }

    buckets = [
        ("Must-pay extras (food, gas, household)", 0.50),
        ("Extra debt payments", 0.20),
        ("Savings / investing", 0.20),
        ("Discretionary", 0.10),
    ]
    out = []
    used = 0.0
    for i, (name, pct) in enumerate(buckets):
        if i == len(buckets) - 1:
            amt = round(leftover - used, 2)
        else:
            amt = round(leftover * pct, 2)
            used += amt
        out.append({"name": name, "amount": amt, "pct": int(pct * 100)})
    return {
        "leftover": round(leftover, 2),
        "note": "Allocated from cash left after unpaid bills this month and your safety buffer.",
        "buckets": out,
        "committed_remaining": remaining_out,
    }


def advice(
    accounts: list[dict],
    obligations: list[dict],
    month_events: list[dict],
    remaining: list[dict],
    lows: list[dict],
    available: float,
    buffer: float,
    today: date,
) -> list[dict]:
    tips: list[dict] = []

    for low in lows:
        if low["type"] not in {"checking", "savings"}:
            continue
        if low["low_balance"] < 0:
            tips.append(
                {
                    "level": "critical",
                    "title": f"{low['account_name']} is projected to overdraft",
                    "body": (
                        f"Projected low is ${low['low_balance']:,.2f} on {low['low_date']}. "
                        "Move money in before that date or skip/shift a discretionary payment."
                    ),
                }
            )
        elif low["low_balance"] < buffer and low["type"] == "checking":
            gap = round(buffer - low["low_balance"], 2)
            savings = next((a for a in accounts if a["type"] == "savings" and a["balance"] >= gap), None)
            move = (
                f" Move ${gap:,.2f} from {savings['name']} before {low['low_date']}."
                if savings
                else f" You need about ${gap:,.2f} more cushion by {low['low_date']}."
            )
            tips.append(
                {
                    "level": "warn",
                    "title": f"{low['account_name']} dips below your ${buffer:,.0f} buffer",
                    "body": f"Projected low is ${low['low_balance']:,.2f} on {low['low_date']}.{move}",
                }
            )

    cards = [a for a in accounts if a["type"] == "credit" and (a.get("apr") or 0) >= 15 and a["balance"] < 0]
    if cards and available > 50:
        extra = min(round(available * 0.2, 2), abs(cards[0]["balance"]))
        tips.append(
            {
                "level": "info",
                "title": f"High-APR debt on {cards[0]['name']}",
                "body": (
                    f"{cards[0]['apr']}% APR on ${abs(cards[0]['balance']):,.2f}. "
                    f"An extra ${extra:,.2f} this month beats parking that cash in brokerage."
                ),
            }
        )

    subs = [
        e
        for e in month_events
        if e.get("category") == "subscriptions" and e["direction"] == "out"
    ]
    sub_total = round(sum(e["amount"] for e in subs), 2)
    if sub_total >= 40:
        names = ", ".join(sorted({e["vendor"] for e in subs}))
        tips.append(
            {
                "level": "info",
                "title": f"${sub_total:,.2f} in subscriptions this month",
                "body": f"{names}. Canceling one unused service is the fastest way to raise safe-to-spend.",
            }
        )

    # Tight cluster: 3+ outflows within 3 days
    outs = [e for e in remaining if e["direction"] == "out"]
    outs.sort(key=lambda e: e["date"])
    for i, e in enumerate(outs):
        cluster = [e]
        d0 = date.fromisoformat(e["date"])
        for other in outs[i + 1 :]:
            if date.fromisoformat(other["date"]) - d0 <= timedelta(days=3):
                cluster.append(other)
            else:
                break
        if len(cluster) >= 3:
            total = round(sum(c["amount"] for c in cluster), 2)
            tips.append(
                {
                    "level": "warn",
                    "title": f"Tight stretch {cluster[0]['date']}–{cluster[-1]['date']}",
                    "body": f"{len(cluster)} payments totaling ${total:,.2f} hit in four days. Keep checking funded before {cluster[0]['date']}.",
                }
            )
            break

    if available < 0:
        tips.append(
            {
                "level": "critical",
                "title": "This month is already over-committed",
                "body": (
                    f"After unpaid bills and a ${buffer:,.0f} buffer, safe-to-spend is ${available:,.2f}. "
                    "Cut a bill, delay a transfer, or bring income forward."
                ),
            }
        )
    elif available < 200:
        tips.append(
            {
                "level": "warn",
                "title": "Very little discretionary room",
                "body": f"Only ${available:,.2f} left after bills and buffer. Treat groceries as the budget, not restaurants.",
            }
        )
    elif not tips:
        tips.append(
            {
                "level": "ok",
                "title": "Cash flow looks stable this month",
                "body": f"${available:,.2f} is left after remaining bills and your buffer. Follow the leftover split rather than raising lifestyle spend.",
            }
        )

    # de-dupe titles
    seen = set()
    uniq = []
    for t in tips:
        if t["title"] in seen:
            continue
        seen.add(t["title"])
        uniq.append(t)
    return uniq[:6]
