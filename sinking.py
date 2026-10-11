"""Sinking funds: monthly reserves for known annual / irregular hits."""

from __future__ import annotations

from datetime import date
from typing import Any

from engine import add_months


def _parse(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def next_due(fund: dict, as_of: date) -> date | None:
    d = _parse(fund.get("next_date"))
    if not d:
        return None
    cad = (fund.get("cadence") or "yearly").lower()
    if d >= as_of:
        return d
    if cad == "once":
        return d
    while d < as_of:
        d = add_months(d, 12)
    return d


def months_until(due: date, as_of: date) -> int:
    n = (due.year - as_of.year) * 12 + (due.month - as_of.month)
    if due.day < as_of.day and n > 0:
        n -= 1
    return max(n, 1)


def enrich(fund: dict, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    target = max(float(fund.get("target_amount") or 0), 0.0)
    reserved = max(float(fund.get("reserved") or 0), 0.0)
    remaining = round(max(target - reserved, 0.0), 2)
    due = next_due(fund, as_of)
    months = months_until(due, as_of) if due else 12
    monthly = round(remaining / months, 2) if remaining else 0.0
    funded = remaining <= 0.01
    days = (due - as_of).days if due else None
    if funded:
        status = "funded"
    elif days is not None and days <= 45 and remaining > 0:
        status = "due_soon"
    elif reserved + monthly * max(months - 1, 0) + 0.01 < target:
        status = "behind"
    else:
        status = "on_track"
    pct = 0.0 if target <= 0 else min(100.0, round(reserved / target * 100.0, 1))
    return {
        **fund,
        "target_amount": target,
        "reserved": reserved,
        "remaining": remaining,
        "due": due.isoformat() if due else None,
        "months_left": months,
        "monthly_need": monthly,
        "funded": funded,
        "status": status,
        "days_left": days,
        "pct": pct,
        "active": int(fund.get("active") or 0),
    }


def portfolio(funds: list[dict], as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    live = [enrich(f, as_of) for f in funds if int(f.get("active") or 0)]
    live.sort(key=lambda f: (f.get("due") or "9999", f["name"].lower()))
    earmarked = round(sum(f["reserved"] for f in live), 2)
    monthly = round(sum(f["monthly_need"] for f in live), 2)
    target = round(sum(f["target_amount"] for f in live), 2)
    behind = [f for f in live if f["status"] in {"behind", "due_soon"}]
    return {
        "items": live,
        "count": len(live),
        "earmarked": earmarked,
        "monthly_need": monthly,
        "target_total": target,
        "behind_count": len(behind),
        "as_of": as_of.isoformat(),
    }


def apply_reserve(con, fund: dict, item: dict, as_of: date) -> tuple[int | None, str]:
    """Create or update the monthly Sink: transfer from checking to dest savings."""
    source = fund.get("account_id")
    dest = fund.get("dest_account_id")
    amt = float(item.get("monthly_need") or 0)
    name = f"Sink: {fund['name']}"
    if not source:
        return fund.get("reserve_obligation_id"), "No source account — set the checking account."
    if amt <= 0:
        rid = fund.get("reserve_obligation_id")
        if rid:
            con.execute(
                "UPDATE obligations SET active=0, end_date=? WHERE id=?",
                (as_of.isoformat(), rid),
            )
            return rid, f"Stopped “{name}” — this fund is reserved."
        return None, "Nothing to reserve."
    due_day = min(as_of.day, 28)
    rid = fund.get("reserve_obligation_id")
    if rid:
        row = con.execute("SELECT id FROM obligations WHERE id=?", (rid,)).fetchone()
        if not row:
            rid = None
    if rid:
        con.execute(
            """UPDATE obligations SET name=?, vendor='Self', account_id=?, dest_account_id=?,
               amount=?, direction='out', cadence='monthly', due_day=?, category='savings',
               active=1, end_date=NULL, notes=? WHERE id=?""",
            (
                name,
                source,
                dest,
                amt,
                due_day,
                f"Sinking reserve for {item.get('due') or fund.get('next_date')}",
                rid,
            ),
        )
        return rid, f"Updated “{name}” to ${amt:,.2f}/mo."
    cur = con.execute(
        """INSERT INTO obligations(
            name, vendor, account_id, dest_account_id, amount, direction,
            cadence, due_day, category, active, notes
        ) VALUES (?, 'Self', ?, ?, ?, 'out', 'monthly', ?, 'savings', 1, ?)""",
        (
            name,
            source,
            dest,
            amt,
            due_day,
            f"Sinking reserve for {item.get('due') or fund.get('next_date')}",
        ),
    )
    return cur.lastrowid, f"Created “{name}” ${amt:,.2f}/mo."


def apply_payout(con, fund: dict, item: dict) -> tuple[int | None, str]:
    """Create or update the yearly vendor hit. Paid from dest if set, else source."""
    pay_from = fund.get("dest_account_id") or fund.get("account_id")
    if not pay_from:
        return fund.get("payout_obligation_id"), "No account to pay the hit from."
    due = item.get("due") or fund.get("next_date")
    if not due:
        return fund.get("payout_obligation_id"), "Set a next date first."
    d = date.fromisoformat(str(due)[:10])
    name = fund["name"]
    pid = fund.get("payout_obligation_id")
    if pid:
        row = con.execute("SELECT id FROM obligations WHERE id=?", (pid,)).fetchone()
        if not row:
            pid = None
    cat = fund.get("category") or "other"
    if pid:
        con.execute(
            """UPDATE obligations SET name=?, vendor=?, account_id=?, dest_account_id=NULL,
               amount=?, direction='out', cadence=?, due_day=?, next_date=?, category=?,
               active=1, notes=? WHERE id=?""",
            (
                name,
                fund.get("vendor") or name,
                pay_from,
                float(fund["target_amount"]),
                fund.get("cadence") or "yearly",
                d.day,
                due,
                cat,
                "Sinking-fund payout",
                pid,
            ),
        )
        return pid, f"Updated payout “{name}” {due} ${float(fund['target_amount']):,.2f}."
    cur = con.execute(
        """INSERT INTO obligations(
            name, vendor, account_id, amount, direction, cadence, due_day, next_date,
            category, active, notes
        ) VALUES (?, ?, ?, ?, 'out', ?, ?, ?, ?, 1, 'Sinking-fund payout')""",
        (
            name,
            fund.get("vendor") or name,
            pay_from,
            float(fund["target_amount"]),
            fund.get("cadence") or "yearly",
            d.day,
            due,
            cat,
        ),
    )
    return cur.lastrowid, f"Created payout “{name}” on {due}."
