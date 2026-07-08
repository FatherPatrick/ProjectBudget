"""Reporting / aggregation layer (phase 4).

Spending is defined as POSITIVE amounts (money out) excluding the
"Transfer/Payment" and "Income" categories, so credit-card payments and
paychecks don't pollute the spend breakdown.

Time ranges are anchored to the most recent transaction in the database by
default (`anchor="latest"`) rather than today's wall clock, because imported
statements usually lag real time. Pass `anchor="today"` for calendar-relative
ranges, or explicit `start`/`end` to override entirely.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta

from .db import db

EXCLUDED_FROM_SPEND = ("Transfer/Payment", "Income")

# range key -> number of days back from the anchor. "all" handled separately.
_RANGE_DAYS = {
    "30d": 30,
    "3mo": 91,
    "6mo": 182,
    "1yr": 365,
}


def _history_floor(conn, account: str | None = None) -> str | None:
    """Start of trustworthy history, or None if there's no data yet.

    Combined view: the latest "earliest transaction" across all imported
    source accounts, so all-time reports only cover the window where every
    source has data (a card whose statements start later would otherwise make
    older months read artificially low). Single-account view: that account's
    own earliest transaction, so filtering by card shows its full history.
    """
    if account and account != "all":
        row = conn.execute(
            "SELECT MIN(txn_date) AS m FROM transactions WHERE source_account = ?",
            (account,),
        ).fetchone()
        return row["m"] if row and row["m"] else None
    row = conn.execute(
        """SELECT MAX(first) AS m FROM (
               SELECT MIN(txn_date) AS first FROM transactions
               GROUP BY source_account
           )"""
    ).fetchone()
    return row["m"] if row and row["m"] else None


def _anchor_date(conn, anchor: str) -> date:
    if anchor == "today":
        return date.today()
    row = conn.execute("SELECT MAX(txn_date) AS m FROM transactions").fetchone()
    return date.fromisoformat(row["m"]) if row and row["m"] else date.today()


def date_bounds(conn, range_key: str, anchor: str,
                start: str | None, end: str | None) -> tuple[str, str]:
    if start and end:
        return start, end
    anchor_d = _anchor_date(conn, anchor)
    end_d = anchor_d
    if range_key == "all":
        start_d = date(1970, 1, 1)
    else:
        days = _RANGE_DAYS.get(range_key, 30)
        start_d = end_d - timedelta(days=days)
    return start_d.isoformat(), end_d.isoformat()


def _where(account: str | None) -> tuple[str, list]:
    clause = "txn_date BETWEEN ? AND ?"
    params: list = []  # start/end prepended by caller
    if account and account != "all":
        clause += " AND source_account = ?"
        params.append(account)
    return clause, params


def build_report(range_key: str = "6mo", account: str | None = None,
                 anchor: str = "latest", start: str | None = None,
                 end: str | None = None, top_n: int = 5) -> dict:
    excluded = ",".join("?" * len(EXCLUDED_FROM_SPEND))
    with db() as conn:
        start, end = date_bounds(conn, range_key, anchor, start, end)

        # Floor history at the start of trustworthy data: combined view uses
        # the window where ALL sources have data; a single account uses its
        # own earliest transaction.
        floor = _history_floor(conn, account)
        clamped = bool(floor and start < floor)
        if clamped:
            start = floor

        acct_clause, acct_params = _where(account)
        base_params = [start, end, *acct_params]

        # Spend by category (positive amounts only, excluding transfers/income).
        by_cat = conn.execute(
            f"""SELECT category,
                       ROUND(SUM(amount), 2) AS total,
                       COUNT(*)             AS txns
                FROM transactions
                WHERE {acct_clause} AND amount > 0
                      AND category NOT IN ({excluded})
                GROUP BY category
                ORDER BY total DESC""",
            [*base_params, *EXCLUDED_FROM_SPEND],
        ).fetchall()
        by_category = [dict(r) for r in by_cat]
        total_spend = round(sum(r["total"] for r in by_category), 2)
        for r in by_category:
            r["pct"] = round(100 * r["total"] / total_spend, 1) if total_spend else 0.0

        # Top N purchases within each spending category.
        top = conn.execute(
            f"""SELECT id, txn_date, description, amount, source_account, category
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (PARTITION BY category
                                              ORDER BY amount DESC, txn_date DESC) AS rn
                    FROM transactions
                    WHERE {acct_clause} AND amount > 0
                          AND category NOT IN ({excluded})
                )
                WHERE rn <= ?
                ORDER BY category, amount DESC""",
            [*base_params, *EXCLUDED_FROM_SPEND, top_n],
        ).fetchall()
        top_per_category: dict[str, list] = {}
        for r in top:
            top_per_category.setdefault(r["category"], []).append(dict(r))

        # Month-over-month spend trend.
        trend = conn.execute(
            f"""SELECT substr(txn_date, 1, 7) AS month,
                       ROUND(SUM(amount), 2)   AS spend
                FROM transactions
                WHERE {acct_clause} AND amount > 0
                      AND category NOT IN ({excluded})
                GROUP BY month
                ORDER BY month""",
            [*base_params, *EXCLUDED_FROM_SPEND],
        ).fetchall()

        # Headline totals.
        income_row = conn.execute(
            f"""SELECT ROUND(-SUM(amount), 2) AS income
                FROM transactions
                WHERE {acct_clause} AND category = 'Income'""",
            base_params,
        ).fetchone()
        txn_count = conn.execute(
            f"SELECT COUNT(*) AS n FROM transactions WHERE {acct_clause}",
            base_params,
        ).fetchone()["n"]

    # Flag months the range only partially covers — they read artificially low.
    monthly_trend = []
    for r in trend:
        row = dict(r)
        month = row["month"]
        last_day = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
        row["partial"] = start > f"{month}-01" or end < f"{month}-{last_day:02d}"
        monthly_trend.append(row)

    income = income_row["income"] or 0.0
    return {
        "range": {"key": range_key, "start": start, "end": end,
                  "anchor": anchor, "account": account or "all",
                  "history_floor": floor, "clamped_to_history_start": clamped},
        "totals": {
            "spend": total_spend,
            "income": income,
            "net": round(income - total_spend, 2),
            "transactions": txn_count,
        },
        "by_category": by_category,
        "top_per_category": top_per_category,
        "monthly_trend": monthly_trend,
    }
