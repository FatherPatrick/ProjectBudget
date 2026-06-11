"""ProjectBudget — local FastAPI app.

Phases 1-3 implemented here: scaffold, CSV import pipeline, and categorization.
Reports API (phase 4) and the web dashboard (phase 5) come next; for now the
JSON endpoints below make the import + categorize flow fully testable.

Run:  run.bat   (or)  python -m uvicorn app.main:app --port 8000
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import categorize as cat
from . import reports
from .db import db, init_db
from .importers import parse_csv_bytes, ParseError, ADAPTERS

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="ProjectBudget", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    format: str | None = Form(default=None),
):
    """Import one or more CSVs. `format` optionally forces an adapter
    (chase_credit | chase_debit | bofa_credit) when auto-detect fails."""
    rules = cat._db_rules()
    results = []
    total_inserted = total_dupes = 0

    for f in files:
        data = await f.read()
        try:
            adapter, records = parse_csv_bytes(data, forced=format)
        except ParseError as e:
            results.append({"file": f.filename, "error": str(e)})
            continue

        inserted = dupes = 0
        with db() as conn:
            for rec in records:
                category = cat.categorize(rec["description"], rec["amount"],
                                          rec["raw_category"], rules)
                try:
                    conn.execute(
                        """INSERT INTO transactions
                             (txn_date, description, amount, source_account,
                              raw_category, category, hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (rec["txn_date"], rec["description"], rec["amount"],
                         rec["source_account"], rec["raw_category"], category,
                         rec["hash"]),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    dupes += 1  # already imported (same hash)

        total_inserted += inserted
        total_dupes += dupes
        results.append({
            "file": f.filename,
            "detected_account": adapter.account,
            "rows_parsed": len(records),
            "inserted": inserted,
            "duplicates_skipped": dupes,
        })

    return {
        "files": results,
        "total_inserted": total_inserted,
        "total_duplicates_skipped": total_dupes,
    }


@app.get("/summary")
def summary():
    """Quick spend-by-category snapshot across all stored data."""
    with db() as conn:
        rows = conn.execute(
            """SELECT category,
                      COUNT(*)            AS txns,
                      ROUND(SUM(amount),2) AS net
               FROM transactions
               GROUP BY category
               ORDER BY net DESC"""
        ).fetchall()
        totals = conn.execute(
            "SELECT COUNT(*) AS n, MIN(txn_date) AS first, MAX(txn_date) AS last "
            "FROM transactions"
        ).fetchone()
    return {
        "transactions": totals["n"],
        "date_range": {"first": totals["first"], "last": totals["last"]},
        "by_category": [dict(r) for r in rows],
    }


@app.get("/transactions")
def transactions(limit: int = 50, category: str | None = None):
    query = "SELECT id, txn_date, description, amount, source_account, category FROM transactions"
    params: list = []
    if category:
        query += " WHERE category = ?"
        params.append(category)
    query += " ORDER BY txn_date DESC, id DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/uncategorized")
def uncategorized(limit: int = 100):
    """Distinct uncategorized descriptions, busiest first — the queue to teach."""
    with db() as conn:
        rows = conn.execute(
            """SELECT description, COUNT(*) AS count, ROUND(SUM(amount),2) AS total
               FROM transactions
               WHERE category = 'Uncategorized'
               GROUP BY description
               ORDER BY count DESC, total DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/rules")
def create_rule(pattern: str = Form(...), category: str = Form(...),
                direction: str = Form(default="any")):
    """Teach the app a rule, then re-apply it to existing transactions.

    direction: 'any' (default) | 'in' (only money-in txns) | 'out' (only spend).
    """
    valid = {c["name"] for c in _categories()}
    if category not in valid:
        raise HTTPException(400, f"Unknown category. Valid: {sorted(valid)}")
    cat.add_rule(pattern, category, direction=direction)
    changed = cat.reapply_all()
    return {"pattern": pattern, "category": category, "direction": direction,
            "transactions_recategorized": changed}


@app.get("/categories")
def _categories():
    with db() as conn:
        rows = conn.execute(
            "SELECT name FROM categories ORDER BY sort_order, name"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/accounts")
def accounts():
    """Distinct source accounts present in the data (for the dashboard filter)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source_account FROM transactions ORDER BY source_account"
        ).fetchall()
    return [r["source_account"] for r in rows]


@app.get("/report")
def report(range: str = "6mo", account: str | None = None,
           anchor: str = "latest", start: str | None = None,
           end: str | None = None, top_n: int = 5):
    """Full report payload: totals, spend-by-category, top-N per category, trend.

    range: 30d | 3mo | 6mo | 1yr | all  (ignored if start & end are given).
    anchor: latest (most recent txn) | today.
    """
    return reports.build_report(range_key=range, account=account, anchor=anchor,
                                 start=start, end=end, top_n=top_n)


@app.post("/transactions/{txn_id}/category")
def set_category(txn_id: int, category: str = Form(...),
                 make_rule: bool = Form(default=False),
                 pattern: str | None = Form(default=None)):
    """Re-categorize a single transaction. Optionally learn a rule from it.

    If make_rule is true, a rule is created from `pattern` (or the transaction's
    full description if no pattern is given) so similar transactions auto-match.
    """
    valid = {c["name"] for c in _categories()}
    if category not in valid:
        raise HTTPException(400, f"Unknown category. Valid: {sorted(valid)}")
    with db() as conn:
        row = conn.execute(
            "SELECT description FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Transaction not found")
        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?", (category, txn_id)
        )

    recategorized = 0
    if make_rule:
        cat.add_rule(pattern or row["description"], category)
        recategorized = cat.reapply_all()
    return {"id": txn_id, "category": category, "rule_created": bool(make_rule),
            "transactions_recategorized": recategorized}
