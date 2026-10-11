"""Daily net-worth snapshots."""

from __future__ import annotations

from datetime import date
from typing import Any


def capture(con, summary: dict, as_of: date | None = None) -> None:
    as_of = as_of or date.today()
    con.execute(
        """INSERT INTO snapshots(as_of, cash, investments, crypto, debt, net_worth)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(as_of) DO UPDATE SET
             cash=excluded.cash,
             investments=excluded.investments,
             crypto=excluded.crypto,
             debt=excluded.debt,
             net_worth=excluded.net_worth""",
        (
            as_of.isoformat(),
            float(summary.get("cash") or 0),
            float(summary.get("investments") or 0),
            float(summary.get("crypto") or 0),
            float(summary.get("debt") or 0),
            float(summary.get("net_worth") or 0),
        ),
    )


def history(con, limit: int = 18) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT * FROM snapshots ORDER BY as_of DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = [dict(r) for r in rows]
    out.reverse()
    return out
