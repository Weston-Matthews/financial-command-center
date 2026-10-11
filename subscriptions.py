"""Subscription kill list: annualize, flag overlaps, cancel/pause and redirect cash."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from engine import add_months, is_obligation_current, month_window

CADENCE_PER_YEAR = {
    "weekly": 52.0,
    "biweekly": 26.0,
    "semimonthly": 24.0,
    "monthly": 12.0,
    "yearly": 1.0,
    "annual": 1.0,
    "once": 0.0,
}

# Soft clusters — two live items in the same cluster = overlap.
CLUSTERS: dict[str, tuple[str, ...]] = {
    "video": (
        "netflix",
        "hulu",
        "disney",
        "max",
        "hbo",
        "paramount",
        "peacock",
        "apple tv",
        "prime video",
        "youtube premium",
        "youtube tv",
        "discovery+",
        "amc+",
    ),
    "music": ("spotify", "apple music", "youtube music", "amazon music", "tidal", "pandora"),
    "cloud": ("icloud", "google one", "dropbox", "onedrive", "icloud+"),
    "fitness": ("gym", "fithaus", "planet fitness", "anytime fitness", "peloton", "classpass"),
    "news": ("nytimes", "new york times", "wsj", "washington post", "substack"),
    "ai": ("chatgpt", "openai", "claude", "anthropic", "midjourney", "github copilot"),
    "gaming": ("xbox", "playstation", "nintendo", "game pass", "steam"),
}

EASY_CANCEL = {
    "netflix",
    "hulu",
    "disney",
    "max",
    "hbo",
    "paramount",
    "peacock",
    "spotify",
    "apple music",
    "youtube",
    "icloud",
    "prime",
    "gym",
    "fithaus",
    "chatgpt",
    "openai",
}

HIGH_ANNUAL = 120.0  # $10/mo starts to matter as a year


def monthly_equivalent(amount: float, cadence: str) -> float:
    per_year = CADENCE_PER_YEAR.get((cadence or "monthly").lower(), 12.0)
    if per_year <= 0:
        return 0.0
    return round(float(amount) * per_year / 12.0, 2)


def annual_equivalent(amount: float, cadence: str) -> float:
    return round(monthly_equivalent(amount, cadence) * 12.0, 2)


def _blob(ob: dict) -> str:
    return f"{ob.get('name') or ''} {ob.get('vendor') or ''} {ob.get('category') or ''}".lower()


def looks_like_subscription(ob: dict) -> bool:
    if (ob.get("direction") or "out") != "out":
        return False
    cat = (ob.get("category") or "").lower()
    if cat == "subscriptions":
        return True
    text = _blob(ob)
    for words in CLUSTERS.values():
        if any(w in text for w in words):
            return True
    return False


def cluster_for(ob: dict) -> str | None:
    text = _blob(ob)
    for name, words in CLUSTERS.items():
        if any(w in text for w in words):
            return name
    return None


def is_easy_cancel(ob: dict) -> bool:
    text = _blob(ob)
    return any(w in text for w in EASY_CANCEL)


def _recent_tx_hit(ob: dict, transactions: list[dict], as_of: date, days: int = 75) -> bool | None:
    """True if an imported tx likely matches this sub. None if no transactions to judge."""
    if not transactions:
        return None
    cutoff = (as_of - timedelta(days=days)).isoformat()
    needles = [p for p in ((ob.get("vendor") or "").lower(), (ob.get("name") or "").lower()) if len(p) >= 3]
    if not needles:
        return None
    for tx in transactions:
        if (tx.get("tx_date") or "") < cutoff:
            continue
        desc = (tx.get("description") or "").lower()
        if any(n in desc for n in needles):
            return True
    return False


def redirect_options(accounts: list[dict], obligations: list[dict], as_of: date) -> list[dict]:
    opts = [
        {"id": "none", "label": "Do not redirect — just stop the charge"},
        {"id": "extra_debt", "label": "Add the monthly amount to extra debt payment"},
    ]
    savings = [a for a in accounts if a.get("type") == "savings"]
    if savings:
        opts.append(
            {
                "id": f"savings:{savings[0]['id']}",
                "label": f"Sweep to {savings[0]['name']}",
            }
        )
    credits = sorted(
        [a for a in accounts if a.get("type") in {"credit", "loan"} and float(a.get("balance") or 0) < 0],
        key=lambda a: float(a.get("apr") or 0),
        reverse=True,
    )
    for a in credits[:4]:
        opts.append(
            {
                "id": f"debt:{a['id']}",
                "label": f"Extra to {a['name']}" + (f" ({a['apr']}% APR)" if a.get("apr") else ""),
            }
        )
    sweeps = [
        o
        for o in obligations
        if is_obligation_current(o, as_of)
        and (o.get("category") or "").lower() == "savings"
        and (o.get("direction") or "out") == "out"
    ]
    for o in sweeps[:2]:
        opts.append({"id": f"obligation:{o['id']}", "label": f"Increase “{o['name']}” by this amount"})
    return opts


def audit(
    obligations: list[dict],
    accounts: list[dict],
    transactions: list[dict] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    transactions = transactions or []
    live = [o for o in obligations if is_obligation_current(o, as_of) and looks_like_subscription(o)]
    items: list[dict[str, Any]] = []
    cluster_counts: dict[str, int] = {}
    for o in live:
        c = cluster_for(o)
        if c:
            cluster_counts[c] = cluster_counts.get(c, 0) + 1

    for o in live:
        monthly = monthly_equivalent(float(o["amount"]), o.get("cadence") or "monthly")
        annual = round(monthly * 12, 2)
        cluster = cluster_for(o)
        flags: list[dict[str, str]] = []
        if annual >= HIGH_ANNUAL:
            flags.append({"code": "high", "label": f"High year cost (${annual:,.0f})"})
        if cluster and cluster_counts.get(cluster, 0) >= 2:
            flags.append({"code": "overlap", "label": f"Overlaps other {cluster} apps"})
        if is_easy_cancel(o):
            flags.append({"code": "easy", "label": "Usually easy to cancel"})
        tx_hit = _recent_tx_hit(o, transactions, as_of)
        if tx_hit is False:
            flags.append({"code": "stale", "label": "No recent statement charge — maybe unused"})
        items.append(
            {
                "id": o["id"],
                "name": o.get("name") or o.get("vendor") or "Subscription",
                "vendor": o.get("vendor") or o.get("name") or "",
                "account_id": o.get("account_id"),
                "amount": float(o["amount"]),
                "cadence": o.get("cadence") or "monthly",
                "due_day": o.get("due_day"),
                "category": o.get("category") or "subscriptions",
                "monthly": monthly,
                "annual": annual,
                "cluster": cluster,
                "flags": flags,
                "priority": (2 if any(f["code"] == "stale" for f in flags) else 0)
                + (2 if any(f["code"] == "overlap" for f in flags) else 0)
                + (1 if any(f["code"] == "high" for f in flags) else 0)
                + (1 if any(f["code"] == "easy" for f in flags) else 0)
                + annual / 1000.0,
            }
        )

    items.sort(key=lambda x: (-x["priority"], -x["annual"], x["name"].lower()))
    monthly_total = round(sum(i["monthly"] for i in items), 2)
    annual_total = round(sum(i["annual"] for i in items), 2)
    overlap_n = sum(1 for i in items if any(f["code"] == "overlap" for f in i["flags"]))
    stale_n = sum(1 for i in items if any(f["code"] == "stale" for f in i["flags"]))
    return {
        "items": items,
        "count": len(items),
        "monthly_total": monthly_total,
        "annual_total": annual_total,
        "overlap_count": overlap_n,
        "stale_count": stale_n,
        "redirects": redirect_options(accounts, obligations, as_of),
        "as_of": as_of.isoformat(),
    }


def _get_ob(con, obligation_id: int) -> dict | None:
    row = con.execute("SELECT * FROM obligations WHERE id=?", (obligation_id,)).fetchone()
    return dict(row) if row else None


def apply_decision(
    con,
    obligation_id: int,
    decision: str,
    redirect: str = "none",
    as_of: date | None = None,
) -> dict[str, Any]:
    """Keep, pause (end of next month), or cancel. Optionally redirect the monthly amount."""
    as_of = as_of or date.today()
    ob = _get_ob(con, obligation_id)
    if not ob:
        raise ValueError("obligation not found")
    decision = (decision or "keep").lower()
    monthly = monthly_equivalent(float(ob["amount"]), ob.get("cadence") or "monthly")
    notes: list[str] = []

    if decision == "keep":
        notes.append("Kept on the kill list.")
    elif decision == "pause":
        _, end = month_window(add_months(as_of.replace(day=1), 1))
        con.execute(
            "UPDATE obligations SET end_date=?, notes=? WHERE id=?",
            (
                end.isoformat(),
                ((ob.get("notes") or "") + f"\nPaused through {end.isoformat()}.").strip(),
                obligation_id,
            ),
        )
        notes.append(f"Paused — last charge allowed {end.isoformat()}.")
    elif decision == "cancel":
        con.execute(
            "UPDATE obligations SET active=0, end_date=?, notes=? WHERE id=?",
            (
                as_of.isoformat(),
                ((ob.get("notes") or "") + f"\nCancelled {as_of.isoformat()} from kill list.").strip(),
                obligation_id,
            ),
        )
        notes.append("Cancelled. Future calendar hits stop after today.")
    else:
        raise ValueError("decision must be keep, pause, or cancel")

    redirect = redirect or "none"
    if decision in {"pause", "cancel"} and redirect and redirect != "none" and monthly > 0:
        notes.append(_apply_redirect(con, ob, monthly, redirect, as_of))

    return {"ok": True, "notes": notes, "monthly": monthly, "decision": decision, "redirect": redirect}


def _apply_redirect(con, ob: dict, monthly: float, redirect: str, as_of: date) -> str:
    if redirect == "extra_debt":
        raw = con.execute("SELECT value FROM settings WHERE key='extra_debt'").fetchone()
        current = float(raw["value"]) if raw and raw["value"] not in ("", None) else 0.0
        new = round(current + monthly, 2)
        con.execute(
            "INSERT INTO settings(key, value) VALUES('extra_debt', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(new),),
        )
        return f"Extra debt payment increased by ${monthly:,.2f}/mo (now ${new:,.2f})."

    kind, _, rest = redirect.partition(":")
    if kind == "obligation" and rest:
        dest_id = int(rest)
        row = con.execute("SELECT * FROM obligations WHERE id=?", (dest_id,)).fetchone()
        if not row:
            return "Redirect target bill was missing."
        new_amt = round(float(row["amount"]) + monthly, 2)
        con.execute("UPDATE obligations SET amount=? WHERE id=?", (new_amt, dest_id))
        return f"Increased “{row['name']}” by ${monthly:,.2f}/mo to ${new_amt:,.2f}."

    if kind == "savings" and rest:
        dest_id = int(rest)
        return _upsert_transfer(
            con,
            ob,
            monthly,
            dest_id,
            name=f"Freed: {ob.get('vendor') or ob.get('name')}",
            category="savings",
            as_of=as_of,
        )

    if kind == "debt" and rest:
        dest_id = int(rest)
        acct = con.execute("SELECT name FROM accounts WHERE id=?", (dest_id,)).fetchone()
        label = acct["name"] if acct else "debt"
        return _upsert_transfer(
            con,
            ob,
            monthly,
            dest_id,
            name=f"Extra to {label}",
            category="debt",
            as_of=as_of,
        )

    return "No redirect applied."


def _upsert_transfer(
    con,
    source_ob: dict,
    monthly: float,
    dest_account_id: int,
    name: str,
    category: str,
    as_of: date,
) -> str:
    existing = con.execute(
        """SELECT * FROM obligations
           WHERE name=? AND account_id=? AND dest_account_id=? AND active=1""",
        (name, source_ob["account_id"], dest_account_id),
    ).fetchone()
    if existing:
        new_amt = round(float(existing["amount"]) + monthly, 2)
        con.execute("UPDATE obligations SET amount=? WHERE id=?", (new_amt, existing["id"]))
        return f"Increased “{name}” by ${monthly:,.2f}/mo to ${new_amt:,.2f}."
    due = int(source_ob["due_day"] or as_of.day)
    con.execute(
        """INSERT INTO obligations(
            name, vendor, account_id, dest_account_id, amount, direction,
            cadence, due_day, category, active, notes
        ) VALUES (?, ?, ?, ?, ?, 'out', 'monthly', ?, ?, 1, ?)""",
        (
            name,
            "Self",
            source_ob["account_id"],
            dest_account_id,
            monthly,
            due,
            category,
            f"Created {as_of.isoformat()} from cancelled/paused subscription.",
        ),
    )
    return f"Created monthly “{name}” ${monthly:,.2f} from the same account."
