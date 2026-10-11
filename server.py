"""Local finance command center API + static UI."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import shutil
import sqlite3
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import allocation
import coach
import db
import debts
import llm_coach
import reconcile
import sinking
import snapshots
import statements
import subscriptions
from engine import build_events, month_window, project_balances, summarize

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Finance Command Center")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AccountIn(BaseModel):
    name: str
    institution: str = ""
    type: str
    balance: float = 0
    apr: float | None = None
    min_payment: float | None = None
    due_day: int | None = None
    currency: str = "USD"
    color: str = ""
    notes: str = ""


class ObligationIn(BaseModel):
    name: str
    vendor: str = ""
    account_id: int
    dest_account_id: int | None = None
    amount: float
    direction: str = "out"
    cadence: str = "monthly"
    due_day: int | None = None
    due_day_2: int | None = None
    weekday: int | None = None
    next_date: str | None = None
    end_date: str | None = None
    category: str = ""
    active: int = 1
    notes: str = ""


class BulkObligationIn(BaseModel):
    name: str
    vendor: str = ""
    account: str = ""  # account name (preferred for bulk paste)
    account_id: int | None = None
    dest_account: str | None = None
    dest_account_id: int | None = None
    amount: float
    direction: str = "out"
    cadence: str = "monthly"
    due_day: int | None = None
    due_day_2: int | None = None
    weekday: int | None = None
    next_date: str | None = None
    end_date: str | None = None
    category: str = ""
    active: int = 1
    notes: str = ""


class BulkImportIn(BaseModel):
    accounts: list[AccountIn] = []
    obligations: list[BulkObligationIn] = []
    replace: bool = False
    buffer: float | None = None
    household: str | None = None


class PaymentIn(BaseModel):
    obligation_id: int
    occur_date: str
    paid: int = 1
    post_balance: bool = False


class SettingsIn(BaseModel):
    buffer: float = Field(ge=0)
    household: str = "Household"
    debt_strategy: str | None = None
    extra_debt: float | None = None
    show_strategy: bool | None = None
    llm_enabled: bool | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    alloc_mode: str | None = None
    alloc_debt_pct: int | None = None
    alloc_safety_pct: int | None = None
    alloc_build_pct: int | None = None
    safety_months: float | None = None
    post_paid: bool | None = None


class CoachIn(BaseModel):
    question: str = ""
    strategy: str | None = None
    extra_debt: float | None = None
    advanced: bool = False


@app.on_event("startup")
def startup() -> None:
    db.init_db(seed=True)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def _state(today: date | None = None) -> dict:
    today = today or date.today()
    horizon_end = today + timedelta(days=45)
    month_start, _ = month_window(today)
    start = min(month_start, today)

    with db.connect() as con:
        accounts = db.rows(con, "SELECT * FROM accounts ORDER BY type, name")
        obligations = db.rows(con, "SELECT * FROM obligations ORDER BY due_day, name")
        payments = db.rows(con, "SELECT * FROM payments")
        transactions = db.rows(con, "SELECT * FROM transactions ORDER BY tx_date DESC LIMIT 800")
        sinking_rows = db.rows(con, "SELECT * FROM sinking_funds ORDER BY next_date, name")
        buffer = float(db.get_setting(con, "buffer", "750") or 750)
        household = db.get_setting(con, "household", "Household")
        demo = db.get_setting(con, "demo", "0") == "1"
        debt_strategy = db.get_setting(con, "debt_strategy", "avalanche") or "avalanche"
        extra_raw = db.get_setting(con, "extra_debt", "")
        show_strategy = db.get_setting(con, "show_strategy", "1") != "0"
        alloc_settings = {
            "alloc_mode": db.get_setting(con, "alloc_mode", "auto") or "auto",
            "alloc_debt_pct": db.get_setting(con, "alloc_debt_pct", ""),
            "alloc_safety_pct": db.get_setting(con, "alloc_safety_pct", ""),
            "alloc_build_pct": db.get_setting(con, "alloc_build_pct", ""),
            "safety_months": db.get_setting(con, "safety_months", "3") or "3",
        }
        post_paid = db.get_setting(con, "post_paid", "0") == "1"
        balances_as_of = db.get_setting(con, "balances_as_of", "") or ""

    events = build_events(accounts, obligations, payments, start, horizon_end)
    series = project_balances(accounts, events, today)
    summary = summarize(accounts, obligations, events, series, today, buffer)
    summary["household"] = household
    summary["demo"] = demo
    summary["debt_strategy"] = debt_strategy
    summary["show_strategy"] = show_strategy
    summary["post_paid"] = post_paid
    summary["balances_as_of"] = balances_as_of or today.isoformat()
    debt_list = debts.debt_accounts(accounts)
    leftover = float((summary.get("budget") or {}).get("leftover") or 0)
    sink = sinking.portfolio(sinking_rows, today)
    alloc = allocation.plan(
        leftover, accounts, obligations, today, alloc_settings, earmarked=sink["earmarked"]
    )
    summary["budget"] = {
        **(summary.get("budget") or {}),
        "leftover": alloc["leftover"],
        "note": alloc["note"],
        "buckets": alloc["buckets"],
        "committed_remaining": (summary.get("budget") or {}).get("committed_remaining"),
    }
    if extra_raw == "":
        extra_debt = max(float(alloc.get("debt_amount") or 0), 0)
        summary["extra_debt_auto"] = True
    else:
        extra_debt = max(float(extra_raw or 0), 0)
        summary["extra_debt_auto"] = False
    summary["extra_debt"] = extra_debt
    plan = debts.simulate(debt_list, debt_strategy, extra_debt, today)
    comparison = debts.compare_strategies(debt_list, extra_debt, today)
    sink_tips = []
    if sink.get("behind_count"):
        names = ", ".join(
            f["name"] for f in sink["items"] if f["status"] in {"behind", "due_soon"}
        )[:80]
        sink_tips.append(
            {
                "level": "warn",
                "title": f"{sink['behind_count']} sinking fund(s) behind",
                "body": (
                    f"{names}. Need {sink['monthly_need']:,.2f}/mo reserved so December "
                    f"(or the next due date) does not raid the emergency fund."
                ),
            }
        )
    summary["advice"] = (allocation.runway_advice(alloc) + sink_tips + list(summary.get("advice") or []))[:7]
    coach_brief = coach.brief(summary, debt_list, plan, obligations, alloc)
    sub_audit = subscriptions.audit(obligations, accounts, transactions, today)
    recon = reconcile.month_report(obligations, transactions, today)
    if recon.get("drifted") or recon.get("missing"):
        bits = []
        if recon["drifted"]:
            bits.append(f"{len(recon['drifted'])} bill(s) charged a different amount")
        if recon["missing"]:
            bits.append(f"{len(recon['missing'])} expected hit(s) not on imported statements")
        summary["advice"] = (
            [
                {
                    "level": "warn",
                    "title": "Statement vs bill book",
                    "body": "; ".join(bits) + ". Review Accounts → This month vs statements.",
                }
            ]
            + list(summary.get("advice") or [])
        )[:7]
    with db.connect() as con:
        snapshots.capture(con, summary, today)
        snap_hist = snapshots.history(con, 18)
        llm_settings = {
            "llm_enabled": db.get_setting(con, "llm_enabled", "0"),
            "llm_provider": db.get_setting(con, "llm_provider", "openai"),
            "llm_base_url": db.get_setting(con, "llm_base_url", ""),
            "llm_model": db.get_setting(con, "llm_model", ""),
            "llm_api_key": db.get_setting(con, "llm_api_key", ""),
        }
    return {
        "summary": summary,
        "accounts": accounts,
        "obligations": obligations,
        "events": events,
        "series": {str(k): v for k, v in series.items()},
        "debts": debt_list,
        "debt_plan": plan,
        "debt_compare": comparison,
        "coach": coach_brief,
        "llm": llm_coach.public_config(llm_settings),
        "subscriptions": sub_audit,
        "allocation": alloc,
        "sinking": sink,
        "reconciliation": recon,
        "snapshots": snap_hist,
    }


@app.get("/api/state")
def api_state(as_of: str | None = None):
    today = date.fromisoformat(as_of) if as_of else date.today()
    return _state(today)


@app.post("/api/accounts")
def create_account(body: AccountIn):
    if body.type not in db.ACCOUNT_TYPES:
        raise HTTPException(400, f"type must be one of {db.ACCOUNT_TYPES}")
    with db.connect() as con:
        cur = con.execute(
            """INSERT INTO accounts(name, institution, type, balance, apr, min_payment, due_day, currency, color, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name,
                body.institution,
                body.type,
                body.balance,
                body.apr,
                body.min_payment,
                body.due_day,
                body.currency,
                body.color,
                body.notes,
            ),
        )
        return {"id": cur.lastrowid}


@app.put("/api/accounts/{account_id}")
def update_account(account_id: int, body: AccountIn):
    with db.connect() as con:
        cur = con.execute(
            """UPDATE accounts SET name=?, institution=?, type=?, balance=?, apr=?, min_payment=?,
               due_day=?, currency=?, color=?, notes=? WHERE id=?""",
            (
                body.name,
                body.institution,
                body.type,
                body.balance,
                body.apr,
                body.min_payment,
                body.due_day,
                body.currency,
                body.color,
                body.notes,
                account_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "account not found")
        db.set_setting(con, "balances_as_of", date.today().isoformat())
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int):
    with db.connect() as con:
        con.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True}


@app.post("/api/obligations")
def create_obligation(body: ObligationIn):
    with db.connect() as con:
        cur = con.execute(
            """INSERT INTO obligations(name, vendor, account_id, dest_account_id, amount, direction,
               cadence, due_day, due_day_2, weekday, next_date, end_date, category, active, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name,
                body.vendor,
                body.account_id,
                body.dest_account_id,
                body.amount,
                body.direction,
                body.cadence,
                body.due_day,
                body.due_day_2,
                body.weekday,
                body.next_date,
                body.end_date,
                body.category,
                body.active,
                body.notes,
            ),
        )
        return {"id": cur.lastrowid}


@app.put("/api/obligations/{obligation_id}")
def update_obligation(obligation_id: int, body: ObligationIn):
    with db.connect() as con:
        cur = con.execute(
            """UPDATE obligations SET name=?, vendor=?, account_id=?, dest_account_id=?, amount=?,
               direction=?, cadence=?, due_day=?, due_day_2=?, weekday=?, next_date=?, end_date=?,
               category=?, active=?, notes=?
               WHERE id=?""",
            (
                body.name,
                body.vendor,
                body.account_id,
                body.dest_account_id,
                body.amount,
                body.direction,
                body.cadence,
                body.due_day,
                body.due_day_2,
                body.weekday,
                body.next_date,
                body.end_date,
                body.category,
                body.active,
                body.notes,
                obligation_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "obligation not found")
    return {"ok": True}


@app.delete("/api/obligations/{obligation_id}")
def delete_obligation(obligation_id: int):
    with db.connect() as con:
        con.execute("DELETE FROM obligations WHERE id=?", (obligation_id,))
    return {"ok": True}


class SubActionIn(BaseModel):
    obligation_id: int
    decision: str  # keep | pause | cancel
    redirect: str = "none"


@app.post("/api/subscriptions/action")
def subscription_action(body: SubActionIn):
    try:
        with db.connect() as con:
            result = subscriptions.apply_decision(
                con, body.obligation_id, body.decision, body.redirect
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.post("/api/payments")
def set_payment(body: PaymentIn):
    with db.connect() as con:
        prev = con.execute(
            "SELECT paid FROM payments WHERE obligation_id=? AND occur_date=?",
            (body.obligation_id, body.occur_date),
        ).fetchone()
        was_paid = int(prev["paid"]) if prev else 0
        con.execute(
            """INSERT INTO payments(obligation_id, occur_date, paid)
               VALUES (?, ?, ?)
               ON CONFLICT(obligation_id, occur_date) DO UPDATE SET paid=excluded.paid""",
            (body.obligation_id, body.occur_date, body.paid),
        )
        post = body.post_balance or db.get_setting(con, "post_paid", "0") == "1"
        if post and was_paid != int(body.paid):
            ob = con.execute("SELECT * FROM obligations WHERE id=?", (body.obligation_id,)).fetchone()
            if ob:
                amt = float(ob["amount"] or 0)
                sign = 1 if int(body.paid) else -1
                if (ob["direction"] or "out") == "out":
                    con.execute(
                        "UPDATE accounts SET balance = balance - ? WHERE id=?",
                        (sign * amt, ob["account_id"]),
                    )
                    if ob["dest_account_id"]:
                        con.execute(
                            "UPDATE accounts SET balance = balance + ? WHERE id=?",
                            (sign * amt, ob["dest_account_id"]),
                        )
                else:
                    con.execute(
                        "UPDATE accounts SET balance = balance + ? WHERE id=?",
                        (sign * amt, ob["account_id"]),
                    )
                db.set_setting(con, "balances_as_of", body.occur_date)
    return {"ok": True}


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    with db.connect() as con:
        db.set_setting(con, "buffer", str(body.buffer))
        db.set_setting(con, "household", body.household)
        if body.debt_strategy:
            db.set_setting(con, "debt_strategy", body.debt_strategy)
        if body.extra_debt is not None:
            db.set_setting(con, "extra_debt", str(body.extra_debt))
        if body.show_strategy is not None:
            db.set_setting(con, "show_strategy", "1" if body.show_strategy else "0")
        if body.llm_enabled is not None:
            db.set_setting(con, "llm_enabled", "1" if body.llm_enabled else "0")
        if body.llm_provider is not None:
            db.set_setting(con, "llm_provider", body.llm_provider)
        if body.llm_base_url is not None:
            db.set_setting(con, "llm_base_url", body.llm_base_url)
        if body.llm_model is not None:
            db.set_setting(con, "llm_model", body.llm_model)
        if body.llm_api_key is not None and body.llm_api_key.strip() and not body.llm_api_key.strip().startswith("••"):
            db.set_setting(con, "llm_api_key", body.llm_api_key.strip())
        if body.alloc_mode is not None:
            db.set_setting(con, "alloc_mode", body.alloc_mode)
        if body.alloc_debt_pct is not None:
            db.set_setting(con, "alloc_debt_pct", str(int(body.alloc_debt_pct)))
        if body.alloc_safety_pct is not None:
            db.set_setting(con, "alloc_safety_pct", str(int(body.alloc_safety_pct)))
        if body.alloc_build_pct is not None:
            db.set_setting(con, "alloc_build_pct", str(int(body.alloc_build_pct)))
        if body.safety_months is not None:
            db.set_setting(con, "safety_months", str(float(body.safety_months)))
        if body.post_paid is not None:
            db.set_setting(con, "post_paid", "1" if body.post_paid else "0")
    return {"ok": True}


class WhatIfIn(BaseModel):
    cancel_ids: list[int] = []
    extra_debt: float | None = None


@app.post("/api/whatif")
def whatif(body: WhatIfIn):
    today = date.today()
    state = _state(today)
    obs = []
    for o in state["obligations"]:
        row = dict(o)
        if row.get("id") in set(body.cancel_ids):
            row["active"] = 0
            row["end_date"] = today.isoformat()
        obs.append(row)
    extra = body.extra_debt
    if extra is None:
        extra = float(state["summary"].get("extra_debt") or 0)
    horizon_end = today + timedelta(days=90)
    month_start, _ = month_window(today)
    start = min(month_start, today)
    events = build_events(state["accounts"], obs, [], start, horizon_end)
    series = project_balances(state["accounts"], events, today)
    summary = summarize(state["accounts"], obs, events, series, today, float(state["summary"].get("buffer") or 750))
    lows = [
        l
        for l in (summary.get("account_lows") or [])
        if l.get("type") in {"checking", "savings"}
    ]
    plan = debts.simulate(state["debts"], state["summary"].get("debt_strategy") or "avalanche", extra, today)
    return {
        "safe_to_spend": summary.get("safe_to_spend"),
        "next30_safe": summary.get("next30_safe"),
        "leftover": (summary.get("budget") or {}).get("leftover"),
        "primary_low": summary.get("primary_low"),
        "account_lows": lows,
        "debt_months": (plan.get("totals") or {}).get("months"),
        "debt_interest": (plan.get("totals") or {}).get("interest"),
        "debt_payoff": (plan.get("totals") or {}).get("payoff_date"),
        "extra_debt": extra,
        "cancelled": body.cancel_ids,
    }


@app.post("/api/whatif/apply")
def whatif_apply(body: WhatIfIn):
    notes = []
    today = date.today()
    with db.connect() as con:
        for oid in body.cancel_ids:
            ob = con.execute("SELECT * FROM obligations WHERE id=?", (oid,)).fetchone()
            if not ob:
                continue
            con.execute(
                "UPDATE obligations SET active=0, end_date=?, notes=? WHERE id=?",
                (
                    today.isoformat(),
                    ((ob["notes"] or "") + f"\nCancelled {today.isoformat()} from what-if.").strip(),
                    oid,
                ),
            )
            notes.append(f"Cancelled {ob['name']}.")
        if body.extra_debt is not None:
            db.set_setting(con, "extra_debt", str(max(float(body.extra_debt), 0)))
            notes.append(f"Extra debt set to ${float(body.extra_debt):,.2f}/mo.")
    return {"ok": True, "notes": notes}


class AdoptAmountIn(BaseModel):
    obligation_id: int
    amount: float


@app.post("/api/reconcile/adopt")
def adopt_amount(body: AdoptAmountIn):
    with db.connect() as con:
        cur = con.execute(
            "UPDATE obligations SET amount=? WHERE id=?",
            (round(float(body.amount), 2), body.obligation_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "obligation not found")
    return {"ok": True}


@app.post("/api/allocation/apply")
def apply_allocation():
    state = _state()
    alloc = state["allocation"]
    with db.connect() as con:
        notes = allocation.apply_jobs(con, alloc)
    return {"ok": True, "notes": notes}


class SinkingIn(BaseModel):
    name: str
    vendor: str = ""
    category: str = "other"
    target_amount: float
    reserved: float = 0
    next_date: str
    cadence: str = "yearly"
    account_id: int | None = None
    dest_account_id: int | None = None
    active: int = 1
    notes: str = ""


def _fund_row(con, fund_id: int) -> dict:
    row = con.execute("SELECT * FROM sinking_funds WHERE id=?", (fund_id,)).fetchone()
    if not row:
        raise HTTPException(404, "sinking fund not found")
    return dict(row)


@app.post("/api/sinking")
def create_sinking(body: SinkingIn):
    with db.connect() as con:
        cur = con.execute(
            """INSERT INTO sinking_funds(
                name, vendor, category, target_amount, reserved, next_date, cadence,
                account_id, dest_account_id, active, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name,
                body.vendor,
                body.category,
                body.target_amount,
                body.reserved,
                body.next_date,
                body.cadence,
                body.account_id,
                body.dest_account_id,
                body.active,
                body.notes,
            ),
        )
        return {"id": cur.lastrowid}


@app.put("/api/sinking/{fund_id}")
def update_sinking(fund_id: int, body: SinkingIn):
    with db.connect() as con:
        _fund_row(con, fund_id)
        con.execute(
            """UPDATE sinking_funds SET name=?, vendor=?, category=?, target_amount=?, reserved=?,
               next_date=?, cadence=?, account_id=?, dest_account_id=?, active=?, notes=?
               WHERE id=?""",
            (
                body.name,
                body.vendor,
                body.category,
                body.target_amount,
                body.reserved,
                body.next_date,
                body.cadence,
                body.account_id,
                body.dest_account_id,
                body.active,
                body.notes,
                fund_id,
            ),
        )
    return {"ok": True}


@app.delete("/api/sinking/{fund_id}")
def delete_sinking(fund_id: int):
    with db.connect() as con:
        _fund_row(con, fund_id)
        con.execute("DELETE FROM sinking_funds WHERE id=?", (fund_id,))
    return {"ok": True}


class SinkingActionIn(BaseModel):
    action: str  # reserve | payout | both


@app.post("/api/sinking/{fund_id}/apply")
def apply_sinking(fund_id: int, body: SinkingActionIn):
    notes = []
    with db.connect() as con:
        fund = _fund_row(con, fund_id)
        item = sinking.enrich(fund)
        rid, pid = fund.get("reserve_obligation_id"), fund.get("payout_obligation_id")
        if body.action in {"reserve", "both"}:
            rid, msg = sinking.apply_reserve(con, fund, item, date.today())
            notes.append(msg)
        if body.action in {"payout", "both"}:
            pid, msg = sinking.apply_payout(con, fund, item)
            notes.append(msg)
        con.execute(
            "UPDATE sinking_funds SET reserve_obligation_id=?, payout_obligation_id=? WHERE id=?",
            (rid, pid, fund_id),
        )
    return {"ok": True, "notes": notes}


@app.post("/api/coach")
def ask_coach(body: CoachIn):
    state = _state()
    plan = state["debt_plan"]
    if body.strategy:
        plan = debts.simulate(
            state["debts"],
            body.strategy,
            body.extra_debt if body.extra_debt is not None else state["summary"]["extra_debt"],
        )
    brief = coach.brief(state["summary"], state["debts"], plan, state["obligations"])
    mode = "local"
    if body.advanced:
        with db.connect() as con:
            enabled = db.get_setting(con, "llm_enabled", "0") == "1"
            provider = db.get_setting(con, "llm_provider", "openai") or "openai"
            meta = llm_coach.PROVIDERS.get(provider, llm_coach.PROVIDERS["openai"])
            base_url = db.get_setting(con, "llm_base_url", "") or meta["base_url"]
            model = db.get_setting(con, "llm_model", "") or meta["default_model"]
            api_key = db.get_setting(con, "llm_api_key", "")
        if not enabled:
            raise HTTPException(400, "Advanced Coach is off. Enable it under Strategy settings.")
        if provider != "ollama" and not api_key.strip():
            raise HTTPException(400, "Add an API key for Advanced Coach (not required for local Ollama).")
        snapshot = llm_coach.build_snapshot(
            state["summary"], state["debts"], plan, state["obligations"], brief
        )
        try:
            reply = llm_coach.chat(
                question=body.question,
                snapshot=snapshot,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            mode = "advanced"
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, str(e)) from e
    else:
        reply = coach.answer(body.question, brief, state["summary"], state["debts"], plan)
    return {"reply": reply, "brief": brief, "mode": mode}


@app.post("/api/reset-demo")
def reset_demo():
    with db.connect() as con:
        con.execute("DELETE FROM sinking_funds")
        con.execute("DELETE FROM snapshots")
        con.execute("DELETE FROM payments")
        con.execute("DELETE FROM obligations")
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM accounts")
        con.execute("DELETE FROM settings")
        db.seed_demo(con)
    return {"ok": True}


@app.post("/api/wipe")
def wipe():
    with db.connect() as con:
        con.execute("DELETE FROM sinking_funds")
        con.execute("DELETE FROM snapshots")
        con.execute("DELETE FROM payments")
        con.execute("DELETE FROM obligations")
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM accounts")
        con.execute("DELETE FROM settings")
        db.set_setting(con, "buffer", "750")
        db.set_setting(con, "demo", "0")
    return {"ok": True}


@app.get("/api/backup")
def backup_db():
    """Download a consistent copy of the SQLite database."""
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not db.DB_PATH.exists():
        raise HTTPException(404, "No database file yet")
    with db.connect() as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    stamp = date.today().isoformat()
    data = db.DB_PATH.read_bytes()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="command-center-backup-{stamp}.db"'
        },
    )


@app.post("/api/restore")
async def restore_db(file: UploadFile = File(...)):
    """Replace the live database with an exported .db backup."""
    raw = await file.read()
    if not raw or len(raw) < 100:
        raise HTTPException(400, "Empty or tiny file")
    if not raw.startswith(b"SQLite format 3"):
        raise HTTPException(400, "File is not a SQLite database")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp_path = Path(tmp.name)
    try:
        tmp.write(raw)
        tmp.close()
        # Validate expected tables exist
        con = sqlite3.connect(tmp_path)
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            con.close()
        required = {"accounts", "obligations", "payments", "settings"}
        missing = required - tables
        if missing:
            raise HTTPException(
                400,
                f"Backup is missing tables: {', '.join(sorted(missing))}. "
                "Export from this app, not a random SQLite file.",
            )

        with db.connect() as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Replace live DB (and drop WAL sidecars)
        for side in (db.DB_PATH, db.DB_PATH.with_suffix(".db-wal"), db.DB_PATH.with_suffix(".db-shm")):
            if side.exists():
                side.unlink()
        shutil.copy2(tmp_path, db.DB_PATH)
        db.init_db(seed=False)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/cleanup")
def cleanup_paid_once():
    """Remove one-time obligations that have been marked paid, plus their payment rows."""
    with db.connect() as con:
        ids = [
            r["id"]
            for r in con.execute(
                """
                SELECT o.id
                FROM obligations o
                WHERE lower(o.cadence) = 'once'
                  AND EXISTS (
                    SELECT 1 FROM payments p
                    WHERE p.obligation_id = o.id AND p.paid = 1
                  )
                """
            ).fetchall()
        ]
        if not ids:
            return {"ok": True, "removed": 0}
        placeholders = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM payments WHERE obligation_id IN ({placeholders})", ids)
        con.execute(f"DELETE FROM obligations WHERE id IN ({placeholders})", ids)
    return {"ok": True, "removed": len(ids)}


@app.post("/api/statements/preview")
async def preview_statement(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    try:
        parsed = statements.parse_upload(file.filename or "statement.csv", data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return parsed


class StatementCommitIn(BaseModel):
    account_id: int
    transactions: list[dict]
    update_balance: bool = True


@app.post("/api/statements/commit")
def commit_statement(body: StatementCommitIn):
    if not body.transactions:
        raise HTTPException(400, "No transactions to import")
    inserted = 0
    skipped = 0
    with db.connect() as con:
        row = con.execute("SELECT id FROM accounts WHERE id=?", (body.account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Account not found")
        for t in body.transactions:
            try:
                cur = con.execute(
                    """INSERT OR IGNORE INTO transactions(
                        account_id, tx_date, description, check_number, amount, balance, source
                    ) VALUES (?, ?, ?, ?, ?, ?, 'csv')""",
                    (
                        body.account_id,
                        t["date"],
                        t.get("description") or "",
                        t.get("check_number") or "",
                        float(t["amount"]),
                        t.get("balance"),
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            except Exception:  # noqa: BLE001
                skipped += 1
        if body.update_balance:
            # Prefer latest statement balance column; else leave account alone
            with_bal = [t for t in body.transactions if t.get("balance") is not None]
            if with_bal:
                latest = sorted(with_bal, key=lambda x: x["date"])[-1]
                con.execute(
                    "UPDATE accounts SET balance=? WHERE id=?",
                    (float(latest["balance"]), body.account_id),
                )
                db.set_setting(con, "balances_as_of", str(latest["date"]))
    return {"ok": True, "inserted": inserted, "skipped": skipped}


@app.get("/api/accounts/{account_id}/transactions")
def list_transactions(account_id: int, limit: int = 100):
    with db.connect() as con:
        rows = db.rows(
            con,
            """SELECT * FROM transactions WHERE account_id=?
               ORDER BY tx_date DESC, id DESC LIMIT ?""",
            (account_id, min(limit, 500)),
        )
    return {"transactions": rows}


@app.post("/api/import")
def bulk_import(body: BulkImportIn):
    """Paste accounts + bills in one shot. Obligations may reference accounts by name."""
    with db.connect() as con:
        if body.replace:
            con.execute("DELETE FROM sinking_funds")
            con.execute("DELETE FROM snapshots")
            con.execute("DELETE FROM payments")
            con.execute("DELETE FROM obligations")
            con.execute("DELETE FROM transactions")
            con.execute("DELETE FROM accounts")
            db.set_setting(con, "demo", "0")

        if body.buffer is not None:
            db.set_setting(con, "buffer", str(body.buffer))
        if body.household:
            db.set_setting(con, "household", body.household)

        name_to_id: dict[str, int] = {
            r["name"]: r["id"] for r in db.rows(con, "SELECT id, name FROM accounts")
        }

        for acct in body.accounts:
            if acct.name in name_to_id:
                con.execute(
                    """UPDATE accounts SET institution=?, type=?, balance=?, apr=?, min_payment=?,
                       due_day=?, currency=?, color=?, notes=? WHERE id=?""",
                    (
                        acct.institution,
                        acct.type,
                        acct.balance,
                        acct.apr,
                        acct.min_payment,
                        acct.due_day,
                        acct.currency,
                        acct.color,
                        acct.notes,
                        name_to_id[acct.name],
                    ),
                )
            else:
                cur = con.execute(
                    """INSERT INTO accounts(name, institution, type, balance, apr, min_payment, due_day, currency, color, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        acct.name,
                        acct.institution,
                        acct.type,
                        acct.balance,
                        acct.apr,
                        acct.min_payment,
                        acct.due_day,
                        acct.currency,
                        acct.color,
                        acct.notes,
                    ),
                )
                name_to_id[acct.name] = cur.lastrowid

        created = 0
        for ob in body.obligations:
            acct_id = ob.account_id
            if not acct_id and ob.account:
                acct_id = name_to_id.get(ob.account)
            if not acct_id:
                raise HTTPException(
                    400,
                    f"Obligation '{ob.name}' needs a valid account name or account_id",
                )
            dest_id = ob.dest_account_id
            if not dest_id and ob.dest_account:
                dest_id = name_to_id.get(ob.dest_account)
            con.execute(
                """INSERT INTO obligations(name, vendor, account_id, dest_account_id, amount, direction,
                   cadence, due_day, due_day_2, weekday, next_date, end_date, category, active, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ob.name,
                    ob.vendor or ob.name,
                    acct_id,
                    dest_id,
                    ob.amount,
                    ob.direction,
                    ob.cadence,
                    ob.due_day,
                    ob.due_day_2,
                    ob.weekday,
                    ob.next_date,
                    ob.end_date,
                    ob.category,
                    ob.active,
                    ob.notes,
                ),
            )
            created += 1

    return {"ok": True, "accounts": len(body.accounts), "obligations": created}
