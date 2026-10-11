"""Parse bank / credit-card statement CSV (and simple Excel) into normalized rows."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

# Header aliases → canonical field
HEADER_MAP = {
    "date": "date",
    "transaction date": "date",
    "posted date": "date",
    "posting date": "date",
    "trans date": "date",
    "description": "description",
    "description/comments": "description",
    "description / comments": "description",
    "comments": "description",
    "memo": "description",
    "payee": "description",
    "narrative": "description",
    "check number": "check_number",
    "check #": "check_number",
    "check": "check_number",
    "amount": "amount",
    "transaction amount": "amount",
    "debit": "debit",
    "credit": "credit",
    "withdrawal": "debit",
    "deposit": "credit",
    "balance": "balance",
    "running balance": "balance",
    "account balance": "balance",
}


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def parse_amount(raw: Any) -> float | None:
    """Parse amounts like ($25.00), $170.00, -25.00, 170, (25.00), CR/DR suffixes."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in {".", "-", "—", "n/a", "N/A"}:
        return None
    s = s.replace(",", "").replace(" ", "")
    s = s.replace("$", "")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    upper = s.upper()
    if upper.endswith("DR"):
        negative = True
        s = s[:-2]
    elif upper.endswith("CR"):
        s = s[:-2]
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        negative = True
        s = s[1:]
    try:
        val = float(s)
    except ValueError:
        return None
    return -abs(val) if negative else val


def parse_date(raw: Any) -> str | None:
    """Return ISO date YYYY-MM-DD or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Excel serial numbers are uncommon in CSV exports; skip if pure int large
    formats = (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # Already ISO-ish
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    return None


def map_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, h in enumerate(headers):
        key = HEADER_MAP.get(_norm_header(h))
        if key and key not in mapping:
            mapping[key] = i
    return mapping


def row_to_tx(fields: list[str], colmap: dict[str, int]) -> dict[str, Any] | None:
    def get(name: str) -> str:
        idx = colmap.get(name)
        if idx is None or idx >= len(fields):
            return ""
        return fields[idx].strip()

    date_iso = parse_date(get("date"))
    if not date_iso:
        return None

    amount = None
    if "amount" in colmap:
        amount = parse_amount(get("amount"))
    if amount is None and ("debit" in colmap or "credit" in colmap):
        debit = parse_amount(get("debit")) or 0.0
        credit = parse_amount(get("credit")) or 0.0
        # Debits as positive numbers in separate columns → outflow
        if debit and not credit:
            amount = -abs(debit)
        elif credit and not debit:
            amount = abs(credit)
        elif debit or credit:
            amount = abs(credit) - abs(debit)
    if amount is None:
        return None

    balance = parse_amount(get("balance")) if "balance" in colmap else None
    desc = get("description") or "(no description)"
    check = get("check_number") or ""

    return {
        "date": date_iso,
        "description": desc,
        "check_number": check,
        "amount": round(amount, 2),
        "balance": round(balance, 2) if balance is not None else None,
    }


def parse_csv_text(text: str) -> dict[str, Any]:
    # Strip BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return {"headers": [], "column_map": {}, "transactions": [], "errors": ["File is empty"]}

    # Find header row: first row that maps to date + amount/debit
    header_idx = 0
    colmap: dict[str, int] = {}
    for i, row in enumerate(rows[:15]):
        trial = map_headers([c for c in row])
        if "date" in trial and ("amount" in trial or "debit" in trial or "credit" in trial):
            header_idx = i
            colmap = trial
            break
    if not colmap:
        return {
            "headers": rows[0] if rows else [],
            "column_map": {},
            "transactions": [],
            "errors": [
                "Could not detect Date + Amount columns. "
                "Expected headers like Date, Description/Comments, Amount, Balance."
            ],
        }

    headers = rows[header_idx]
    txs: list[dict] = []
    errors: list[str] = []
    for n, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not row or all(not str(c).strip() for c in row):
            continue
        # Skip repeated header lines
        if map_headers(row) == colmap:
            continue
        try:
            tx = row_to_tx([str(c) for c in row], colmap)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Line {n}: {e}")
            continue
        if tx is None:
            errors.append(f"Line {n}: could not parse date/amount")
            continue
        txs.append(tx)

    # Newest first often; sort ascending by date for import stability
    txs.sort(key=lambda t: (t["date"], t["description"]))

    credits = round(sum(t["amount"] for t in txs if t["amount"] > 0), 2)
    debits = round(sum(t["amount"] for t in txs if t["amount"] < 0), 2)
    latest_balance = None
    if txs:
        with_bal = [t for t in txs if t.get("balance") is not None]
        if with_bal:
            # Prefer the transaction with the latest date that has a balance
            latest_balance = sorted(with_bal, key=lambda t: t["date"])[-1]["balance"]

    return {
        "headers": headers,
        "column_map": colmap,
        "transactions": txs,
        "errors": errors[:20],
        "summary": {
            "count": len(txs),
            "credits": credits,
            "debits": debits,
            "net": round(credits + debits, 2),
            "latest_balance": latest_balance,
            "date_min": txs[0]["date"] if txs else None,
            "date_max": txs[-1]["date"] if txs else None,
        },
    }


def parse_upload(filename: str, data: bytes) -> dict[str, Any]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        try:
            import openpyxl  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Excel support needs openpyxl. Run: poetry add openpyxl"
            ) from e
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if c is None else c for c in row])
        return parse_csv_text(buf.getvalue())

    # Try utf-8 then common Windows export encodings
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")
    return parse_csv_text(text)
