"""CSV import pipeline.

Each bank exports a differently-shaped CSV. An adapter per source detects its
format from the header row and normalizes rows into one common schema:

    {txn_date, description, amount, source_account, raw_category, hash}

Sign convention (normalized): amount POSITIVE = money spent (outflow),
NEGATIVE = money in (income / refund / payment). All three supported banks use
"negative = outflow" in their raw CSV, so we flip the sign uniformly, but each
adapter declares it explicitly in case a format changes.
"""
from __future__ import annotations
import csv
import io
import hashlib
from datetime import datetime

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y")


class ParseError(Exception):
    pass


def _parse_date(value: str) -> str:
    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ParseError(f"Unrecognized date format: {value!r}")


def _parse_amount(value: str) -> float:
    value = (value or "").strip().replace("$", "").replace(",", "")
    if value in ("", "-", "--"):
        raise ParseError("empty amount")
    # Handle parenthesized negatives, e.g. "(12.34)".
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    return float(value)


def _make_hash(account: str, date: str, amount: float, description: str) -> str:
    key = f"{account}|{date}|{amount:.2f}|{description.strip().upper()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class Adapter:
    name = "base"
    account = "Unknown"
    signature: set[str] = set()   # required (lowercased) header columns
    date_col = ""
    desc_col = ""
    amount_col = ""
    rawcat_col: str | None = None
    flip_sign = True              # normalized = -raw (raw uses negative=outflow)

    def score(self, header: set[str]) -> int:
        """Higher = better match. 0 means this adapter does not apply."""
        return len(self.signature) if self.signature <= header else 0

    def parse_row(self, row: dict[str, str]) -> dict | None:
        try:
            date = _parse_date(row.get(self.date_col, ""))
            raw_amount = _parse_amount(row.get(self.amount_col, ""))
        except ParseError:
            return None  # skip blank/summary/footer lines silently
        description = (row.get(self.desc_col, "") or "").strip()
        if not description:
            return None
        amount = -raw_amount if self.flip_sign else raw_amount
        raw_category = (row.get(self.rawcat_col, "") or "").strip() if self.rawcat_col else ""
        return {
            "txn_date": date,
            "description": description,
            "amount": round(amount, 2),
            "source_account": self.account,
            "raw_category": raw_category,
            "hash": _make_hash(self.account, date, amount, description),
        }


class ChaseCreditAdapter(Adapter):
    name = "chase_credit"
    account = "Chase Credit Card"
    signature = {"transaction date", "post date", "description", "amount"}
    date_col = "transaction date"
    desc_col = "description"
    amount_col = "amount"
    rawcat_col = "category"


class ChaseDebitAdapter(Adapter):
    name = "chase_debit"
    account = "Chase Debit"
    signature = {"details", "posting date", "description", "amount"}
    date_col = "posting date"
    desc_col = "description"
    amount_col = "amount"


class BofaCreditAdapter(Adapter):
    name = "bofa_credit"
    account = "Bank of America Credit Card"
    signature = {"posted date", "reference number", "payee", "amount"}
    date_col = "posted date"
    desc_col = "payee"
    amount_col = "amount"


ADAPTERS: list[Adapter] = [
    ChaseCreditAdapter(),
    ChaseDebitAdapter(),
    BofaCreditAdapter(),
]
ADAPTERS_BY_NAME = {a.name: a for a in ADAPTERS}


def _best_adapter(header: list[str], forced: str | None) -> Adapter | None:
    if forced:
        return ADAPTERS_BY_NAME.get(forced)
    header_set = set(header)
    best, best_score = None, 0
    for adapter in ADAPTERS:
        s = adapter.score(header_set)
        if s > best_score:
            best, best_score = adapter, s
    return best


def parse_csv_bytes(data: bytes, forced: str | None = None) -> tuple[Adapter, list[dict]]:
    """Detect the bank format and return (adapter, normalized_records).

    Tolerates a BOM and any leading preamble/summary lines that some banks
    prepend before the real header row.
    """
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ParseError("Empty file")

    for i, raw_header in enumerate(rows):
        header = [c.strip().lower() for c in raw_header]
        adapter = _best_adapter(header, forced)
        if adapter and (forced or adapter.score(set(header)) > 0):
            records: list[dict] = []
            for raw in rows[i + 1:]:
                if not any(c.strip() for c in raw):
                    continue
                row = dict(zip(header, raw))
                rec = adapter.parse_row(row)
                if rec:
                    records.append(rec)
            return adapter, records

    raise ParseError(
        "Could not detect a supported bank format (Chase credit, Chase debit, "
        "or Bank of America credit). Check the CSV header row."
    )
