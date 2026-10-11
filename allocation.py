"""Assign leftover to three jobs: Debt extra, Safety, Build."""

from __future__ import annotations

from datetime import date
from typing import Any

from engine import is_obligation_current
from subscriptions import monthly_equivalent

HIGH_APR = 15.0
JOB_NAMES = {
    "debt": "Debt extra",
    "safety": "Safety",
    "build": "Build",
}
TRANSFER_NAMES = {
    "safety": "Leftover: Safety",
    "build": "Leftover: Build",
}


def _monthly_out(ob: dict) -> float:
    if (ob.get("direction") or "out") != "out":
        return 0.0
    return monthly_equivalent(float(ob.get("amount") or 0), ob.get("cadence") or "monthly")


def is_allocation_transfer(ob: dict) -> bool:
    name = ob.get("name") or ""
    return name.startswith("Leftover:") or name.startswith("Sink:")


def _counts_as_fixed(ob: dict, as_of: date) -> bool:
    if not is_obligation_current(ob, as_of):
        return False
    if is_allocation_transfer(ob):
        return False
    if (ob.get("direction") or "out") != "out":
        return False
    cat = (ob.get("category") or "").lower()
    if cat in {"savings", "income"}:
        return False
    return _monthly_out(ob) > 0


def fixed_breakdown(obligations: list[dict], as_of: date) -> list[dict[str, Any]]:
    items = []
    for ob in obligations:
        if not _counts_as_fixed(ob, as_of):
            continue
        monthly = _monthly_out(ob)
        items.append(
            {
                "id": ob.get("id"),
                "name": ob.get("name") or ob.get("vendor") or "Bill",
                "vendor": ob.get("vendor") or "",
                "category": (ob.get("category") or "other").lower() or "other",
                "monthly": monthly,
            }
        )
    items.sort(key=lambda x: (-x["monthly"], x["name"].lower()))
    return items


def fixed_monthly(obligations: list[dict], as_of: date) -> float:
    """Required recurring outflow used for runway. Skips savings sweeps and leftover jobs."""
    return round(sum(i["monthly"] for i in fixed_breakdown(obligations, as_of)), 2)


def category_totals(items: list[dict]) -> list[dict[str, Any]]:
    bags: dict[str, float] = {}
    for i in items:
        bags[i["category"]] = round(bags.get(i["category"], 0.0) + i["monthly"], 2)
    return [{"category": k, "monthly": v} for k, v in sorted(bags.items(), key=lambda kv: -kv[1])]


def runway_status(runway: float | None, target: float) -> str:
    if runway is None:
        return "unknown"
    if runway <= 0:
        return "empty"
    if runway < max(target * 0.5, 1.0):
        return "critical"
    if runway < target:
        return "short"
    if runway < target + 3:
        return "ok"
    return "strong"


def savings_cash(accounts: list[dict], earmarked: float = 0.0) -> float:
    raw = sum(float(a.get("balance") or 0) for a in accounts if a.get("type") == "savings")
    return round(max(raw - max(float(earmarked or 0), 0.0), 0.0), 2)


def months_of_runway(savings: float, fixed: float) -> float | None:
    if fixed <= 0:
        return None
    return round(savings / fixed, 2)


def high_apr_debts(accounts: list[dict]) -> list[dict]:
    out = []
    for a in accounts:
        if a.get("type") not in {"credit", "loan"}:
            continue
        if float(a.get("balance") or 0) >= 0:
            continue
        if float(a.get("apr") or 0) >= HIGH_APR:
            out.append(a)
    return out


def has_debt(accounts: list[dict]) -> bool:
    return any(
        a.get("type") in {"credit", "loan"} and float(a.get("balance") or 0) < 0 for a in accounts
    )


def first_account(accounts: list[dict], types: tuple[str, ...]) -> dict | None:
    for a in accounts:
        if a.get("type") in types:
            return a
    return None


def recommend_percents(
    accounts: list[dict],
    runway: float | None,
    target_months: float,
) -> tuple[dict[str, int], str]:
    """Return debt/safety/build percents and a short why."""
    debt_ok = has_debt(accounts)
    hot = bool(high_apr_debts(accounts))
    short_ef = runway is None or runway < target_months
    invest = first_account(accounts, ("brokerage", "crypto"))

    if hot and debt_ok:
        if short_ef:
            pcts = {"debt": 60, "safety": 30, "build": 10}
            why = (
                f"Something is at {HIGH_APR:.0f}%+ APR, and savings cover "
                f"{runway if runway is not None else 0:.1f} months of fixed bills "
                f"(target {target_months:.0f}). Most leftover attacks the expensive balance; "
                "a slice still funds the floor."
            )
        else:
            pcts = {"debt": 80, "safety": 10, "build": 10}
            why = (
                f"High-APR debt is the most expensive hole. Floor looks funded "
                f"({runway:.1f} months). Extra goes to the card/loan, not the market."
            )
    elif short_ef:
        pcts = {"debt": 20 if debt_ok else 0, "safety": 70 if debt_ok else 90, "build": 10}
        if not debt_ok:
            pcts = {"debt": 0, "safety": 90, "build": 10}
        why = (
            f"No high-APR fire, but the emergency fund is short of {target_months:.0f} months "
            f"of fixed bills ({runway if runway is not None else 0:.1f} now). Safety gets the job."
        )
    elif debt_ok:
        pcts = {"debt": 40, "safety": 10, "build": 50}
        why = (
            f"Floor is at {runway:.1f} months and APRs are milder. "
            "Split leftover between extra principal and Build."
        )
    else:
        pcts = {"debt": 0, "safety": 15, "build": 85}
        why = (
            f"No revolving/loan balances and runway is {runway:.1f} months. "
            "Leftover’s job is Build, with a small safety top-up."
        )
    if not invest and pcts["build"]:
        # Park Build in safety if there is nowhere to invest yet.
        pcts["safety"] += pcts["build"]
        pcts["build"] = 0
        why += " No brokerage/crypto account yet, so Build is parked in Safety."
    # normalize
    s = pcts["debt"] + pcts["safety"] + pcts["build"]
    if s != 100 and s > 0:
        pcts["safety"] += 100 - s
    return pcts, why


def split_amounts(leftover: float, pcts: dict[str, int]) -> list[dict[str, Any]]:
    leftover = max(round(float(leftover or 0), 2), 0.0)
    keys = ("debt", "safety", "build")
    used = 0.0
    rows = []
    for i, key in enumerate(keys):
        pct = int(pcts.get(key) or 0)
        if i == len(keys) - 1:
            amt = round(leftover - used, 2)
        else:
            amt = round(leftover * pct / 100.0, 2)
            used += amt
        rows.append(
            {
                "key": key,
                "name": JOB_NAMES[key],
                "pct": pct,
                "amount": amt,
            }
        )
    return rows


def plan(
    leftover: float,
    accounts: list[dict],
    obligations: list[dict],
    as_of: date,
    settings: dict[str, str] | None = None,
    earmarked: float = 0.0,
) -> dict[str, Any]:
    settings = settings or {}
    target = float(settings.get("safety_months") or 3) or 3.0
    mode = (settings.get("alloc_mode") or "auto").lower()
    fixed = fixed_monthly(obligations, as_of)
    savings = savings_cash(accounts, earmarked)
    runway = months_of_runway(savings, fixed)
    rec, why = recommend_percents(accounts, runway, target)

    if mode == "manual":
        pcts = {
            "debt": int(float(settings.get("alloc_debt_pct") or rec["debt"])),
            "safety": int(float(settings.get("alloc_safety_pct") or rec["safety"])),
            "build": int(float(settings.get("alloc_build_pct") or rec["build"])),
        }
        total = pcts["debt"] + pcts["safety"] + pcts["build"]
        if total <= 0:
            pcts, why = rec, why
            mode = "auto"
        elif total != 100:
            # keep user ratios, scale
            pcts = {k: int(round(v * 100 / total)) for k, v in pcts.items()}
            pcts["safety"] += 100 - sum(pcts.values())
    else:
        pcts = rec

    buckets = split_amounts(leftover, pcts)
    by_key = {b["key"]: b for b in buckets}
    gap_months = None
    if runway is None:
        gap_months = target
    elif runway < target:
        gap_months = round(target - runway, 2)
    safety_gap_cash = round(max(target * fixed - savings, 0), 2) if fixed else 0.0
    safety_amt = by_key["safety"]["amount"]
    months_to_target = None
    if safety_gap_cash > 0 and safety_amt > 0:
        months_to_target = round(safety_gap_cash / safety_amt, 1)
    bills = fixed_breakdown(obligations, as_of)
    savings_accounts = [
        {"id": a["id"], "name": a["name"], "balance": round(float(a.get("balance") or 0), 2)}
        for a in accounts
        if a.get("type") == "savings"
    ]
    status = runway_status(runway, target)
    headlines = {
        "unknown": "Add recurring bills to measure runway.",
        "empty": "Emergency fund is empty against your fixed bills.",
        "critical": "Runway is thin. Do not raid savings for extra debt or investing.",
        "short": "Below target. Safety leftover should hit the fund before Build.",
        "ok": "Floor is funded. Extra debt and Build can share leftover.",
        "strong": "More than three months past target. Floor is not the constraint.",
    }

    note = (
        "Leftover is cash after unpaid bills and the checking buffer. "
        "These three jobs are the plan for that slack — not a second grocery budget."
    )
    if leftover <= 0:
        note = "No leftover after committed bills and buffer. Nothing to assign this month."

    return {
        "leftover": round(max(leftover, 0), 2),
        "note": note,
        "why": why,
        "mode": mode,
        "recommended": rec,
        "buckets": buckets,
        "debt_amount": by_key["debt"]["amount"],
        "safety_amount": by_key["safety"]["amount"],
        "build_amount": by_key["build"]["amount"],
        "fixed_monthly": fixed,
        "savings": savings,
        "runway_months": runway,
        "safety_months_target": target,
        "safety_gap_cash": safety_gap_cash,
        "gap_months": gap_months,
        "high_apr": [
            {"id": a["id"], "name": a["name"], "apr": a.get("apr"), "balance": a.get("balance")}
            for a in high_apr_debts(accounts)
        ],
        "dest_safety": (first_account(accounts, ("savings",)) or {}).get("id"),
        "dest_build": (first_account(accounts, ("brokerage", "crypto")) or {}).get("id"),
        "source": (first_account(accounts, ("checking",)) or {}).get("id"),
        "runway": {
            "months": runway,
            "target": target,
            "status": status,
            "headline": headlines[status],
            "fixed_monthly": fixed,
            "savings": savings,
            "gap_cash": safety_gap_cash,
            "gap_months": gap_months,
            "safety_monthly": safety_amt,
            "months_to_target": months_to_target,
            "bills": bills,
            "categories": category_totals(bills),
            "accounts": savings_accounts,
            "pct_of_target": (
                None if runway is None or target <= 0 else round(min(runway / target * 100.0, 999), 1)
            ),
        },
    }


def runway_advice(alloc: dict[str, Any]) -> list[dict[str, str]]:
    r = alloc.get("runway") or {}
    status = r.get("status") or "unknown"
    months = r.get("months")
    target = r.get("target") or 3
    gap = r.get("gap_cash") or 0
    eta = r.get("months_to_target")
    level = {
        "empty": "critical",
        "critical": "critical",
        "short": "warn",
        "ok": "ok",
        "strong": "ok",
        "unknown": "info",
    }.get(status, "info")
    mo = f"{months:.1f}" if months is not None else "—"
    eta_bit = (
        f" At the current Safety job ({_fmt(r.get('safety_monthly') or 0)}/mo) that gap closes in about {eta} months."
        if eta
        else ""
    )
    body = (
        f"Savings {_fmt(r.get('savings') or 0)} cover {mo} months of "
        f"{_fmt(r.get('fixed_monthly') or 0)} fixed bills. Target is {target:.0f} months."
    )
    if gap > 0:
        body += f" Still short {_fmt(gap)}.{eta_bit}"
    else:
        body += " Checking buffer is operating cash — this meter is the savings floor only."
    return [
        {
            "level": level,
            "title": f"Emergency fund: {mo} / {target:.0f} months",
            "body": body,
        }
    ]


def _fmt(n: float) -> str:
    return f"${float(n):,.2f}"


def apply_jobs(con, alloc: dict[str, Any], as_of: date | None = None) -> list[str]:
    """Write extra_debt + Safety/Build transfer obligations to match this month’s plan."""
    as_of = as_of or date.today()
    notes = []
    debt_amt = float(alloc.get("debt_amount") or 0)
    con.execute(
        "INSERT INTO settings(key, value) VALUES('extra_debt', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(round(debt_amt, 2)),),
    )
    notes.append(f"Extra debt payment set to ${debt_amt:,.2f}/mo.")

    source_id = alloc.get("source")
    if not source_id:
        notes.append("No checking account — could not create Safety/Build transfers.")
        return notes

    due = as_of.day if as_of.day <= 28 else 28
    pairs = [
        ("safety", alloc.get("dest_safety"), "savings"),
        ("build", alloc.get("dest_build"), "savings"),
    ]
    for key, dest_id, category in pairs:
        name = TRANSFER_NAMES[key]
        amt = float(alloc.get(f"{key}_amount") or 0)
        if not dest_id or amt <= 0:
            existing = con.execute(
                "SELECT id FROM obligations WHERE name=? AND account_id=?",
                (name, source_id),
            ).fetchone()
            if existing and amt <= 0:
                con.execute(
                    "UPDATE obligations SET active=0, end_date=? WHERE id=?",
                    (as_of.isoformat(), existing["id"]),
                )
                notes.append(f"Stopped “{name}” (bucket is $0).")
            continue
        if key == "build":
            category = "savings"
        existing = con.execute(
            "SELECT id, amount FROM obligations WHERE name=? AND account_id=? AND active=1",
            (name, source_id),
        ).fetchone()
        if existing:
            con.execute(
                "UPDATE obligations SET amount=?, dest_account_id=?, category=?, due_day=?, cadence='monthly', direction='out' WHERE id=?",
                (round(amt, 2), dest_id, category, due, existing["id"]),
            )
            notes.append(f"Updated “{name}” to ${amt:,.2f}/mo.")
        else:
            con.execute(
                """INSERT INTO obligations(
                    name, vendor, account_id, dest_account_id, amount, direction,
                    cadence, due_day, category, active, notes
                ) VALUES (?, 'Self', ?, ?, ?, 'out', 'monthly', ?, ?, 1, ?)""",
                (
                    name,
                    source_id,
                    dest_id,
                    round(amt, 2),
                    due,
                    category,
                    f"Created {as_of.isoformat()} from leftover assignment.",
                ),
            )
            notes.append(f"Created “{name}” ${amt:,.2f}/mo.")
    return notes
