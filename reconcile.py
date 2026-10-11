"""Match imported statement lines to this month’s bill-book hits."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from engine import is_obligation_current, month_window, occurrences_for


def _needles(ob: dict) -> list[str]:
    out = []
    for raw in (ob.get("vendor") or "", ob.get("name") or ""):
        s = raw.strip().lower()
        if len(s) >= 3:
            out.append(s)
    return out


def _desc_hit(desc: str, needles: list[str]) -> bool:
    d = (desc or "").lower()
    return any(n in d for n in needles)


def _amount_close(expected: float, tx_amt: float, direction: str) -> bool:
    signed = -abs(expected) if direction != "in" else abs(expected)
    if direction == "in" and tx_amt <= 0:
        return False
    if direction != "in" and tx_amt >= 0:
        return False
    diff = abs(abs(tx_amt) - expected)
    return diff <= max(2.0, expected * 0.15)


def month_report(
    obligations: list[dict],
    transactions: list[dict],
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    start, end = month_window(as_of)
    pad_start = start - timedelta(days=10)
    month_txs = [
        t
        for t in transactions
        if pad_start.isoformat() <= (t.get("tx_date") or "") <= end.isoformat()
    ]
    used: set[int] = set()
    matches: list[dict] = []
    missing: list[dict] = []
    drifted: list[dict] = []

    live = [
        o
        for o in obligations
        if is_obligation_current(o, as_of) or occurrences_for(o, start, end)
    ]
    for ob in live:
        dates = occurrences_for(ob, start, end)
        if not dates:
            continue
        needles = _needles(ob)
        expected = float(ob.get("amount") or 0)
        direction = ob.get("direction") or "out"
        for occur in dates:
            window_lo = (occur - timedelta(days=10)).isoformat()
            window_hi = (occur + timedelta(days=10)).isoformat()
            candidates = []
            for t in month_txs:
                tid = t.get("id")
                if tid in used:
                    continue
                if t.get("account_id") != ob.get("account_id"):
                    continue
                if not (window_lo <= (t.get("tx_date") or "") <= window_hi):
                    continue
                if needles and not _desc_hit(t.get("description") or "", needles):
                    continue
                candidates.append(t)
            if not candidates and needles:
                # looser: same account + month + name, ignore exact day
                for t in month_txs:
                    tid = t.get("id")
                    if tid in used:
                        continue
                    if t.get("account_id") != ob.get("account_id"):
                        continue
                    if not (start.isoformat() <= (t.get("tx_date") or "") <= end.isoformat()):
                        continue
                    if _desc_hit(t.get("description") or "", needles):
                        candidates.append(t)
            best = None
            if candidates:
                best = min(
                    candidates,
                    key=lambda t: (
                        0 if _amount_close(expected, float(t.get("amount") or 0), direction) else 1,
                        abs(abs(float(t.get("amount") or 0)) - expected),
                    ),
                )
            row = {
                "obligation_id": ob.get("id"),
                "name": ob.get("name") or ob.get("vendor"),
                "vendor": ob.get("vendor") or "",
                "occur_date": occur.isoformat(),
                "expected": expected,
                "direction": direction,
                "account_id": ob.get("account_id"),
                "category": ob.get("category") or "",
            }
            if not best:
                if occur <= as_of:
                    missing.append(row)
                continue
            used.add(best.get("id"))
            actual = float(best.get("amount") or 0)
            close = _amount_close(expected, actual, direction)
            row.update(
                {
                    "tx_id": best.get("id"),
                    "tx_date": best.get("tx_date"),
                    "tx_description": best.get("description") or "",
                    "actual": abs(actual),
                    "actual_signed": actual,
                    "close": close,
                }
            )
            if close:
                matches.append(row)
            else:
                drifted.append(row)

    unplanned = []
    for t in month_txs:
        if t.get("id") in used:
            continue
        if (t.get("tx_date") or "") < start.isoformat():
            continue
        amt = float(t.get("amount") or 0)
        if abs(amt) < 1:
            continue
        unplanned.append(
            {
                "tx_id": t.get("id"),
                "account_id": t.get("account_id"),
                "tx_date": t.get("tx_date"),
                "description": t.get("description") or "",
                "amount": amt,
            }
        )
    unplanned.sort(key=lambda x: abs(x["amount"]), reverse=True)
    unplanned_out = round(sum(-t["amount"] for t in unplanned if t["amount"] < 0), 2)
    return {
        "month": start.strftime("%Y-%m"),
        "matched": len(matches),
        "missing": missing,
        "drifted": drifted,
        "unplanned": unplanned[:25],
        "unplanned_out": unplanned_out,
        "hits": matches,
        "tx_count": len([t for t in transactions if start.isoformat() <= (t.get("tx_date") or "") <= end.isoformat()]),
    }
