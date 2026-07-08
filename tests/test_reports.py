from app.db import db
from app.reports import build_report

_counter = iter(range(10_000))


def _insert(conn, date, desc, amount, account="Chase Debit", category="Food"):
    conn.execute(
        """INSERT INTO transactions
             (txn_date, description, amount, source_account, category, hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (date, desc, amount, account, category, f"h{next(_counter)}"),
    )


def test_spend_excludes_income_and_transfers():
    with db() as conn:
        _insert(conn, "2026-06-01", "STARBUCKS", 5.75, category="Food")
        _insert(conn, "2026-06-02", "PAYROLL", -2000.00, category="Income")
        _insert(conn, "2026-06-03", "CARD PAYMENT", 500.00, category="Transfer/Payment")

    r = build_report(range_key="all")
    assert r["totals"]["spend"] == 5.75
    assert r["totals"]["income"] == 2000.00
    assert r["totals"]["net"] == 1994.25
    assert [c["category"] for c in r["by_category"]] == ["Food"]


def test_history_floor_is_where_all_sources_have_data():
    with db() as conn:
        # Chase credit reaches back to January, debit to March, BofA to May.
        _insert(conn, "2026-01-15", "OLD CC PURCHASE", 20.0,
                account="Chase Credit Card")
        _insert(conn, "2026-03-01", "PAYROLL", -2000.0, category="Income")
        _insert(conn, "2026-05-01", "BOFA PURCHASE", 30.0,
                account="Bank of America Credit Card")
        _insert(conn, "2026-05-05", "STARBUCKS", 5.0)

    r = build_report(range_key="all")
    assert r["range"]["clamped_to_history_start"] is True
    assert r["range"]["start"] == "2026-05-01"   # latest source start wins
    # Only spending inside the common window counts.
    assert r["totals"]["spend"] == 35.0


def test_single_account_filter_uses_that_accounts_full_history():
    with db() as conn:
        _insert(conn, "2026-01-15", "OLD CC PURCHASE", 20.0,
                account="Chase Credit Card")
        _insert(conn, "2026-05-01", "BOFA PURCHASE", 30.0,
                account="Bank of America Credit Card")

    r = build_report(range_key="all", account="Chase Credit Card")
    # Filtering by card shows its whole history, not the common window.
    assert r["range"]["start"] == "2026-01-15"
    assert r["totals"]["spend"] == 20.0


def test_no_clamp_when_range_is_within_common_history():
    with db() as conn:
        _insert(conn, "2026-03-01", "PAYROLL", -2000.0, category="Income")
        _insert(conn, "2026-06-05", "STARBUCKS", 5.0)

    r = build_report(range_key="30d")  # anchored to latest txn (2026-06-05)
    assert r["range"]["clamped_to_history_start"] is False


def test_partial_month_flags():
    with db() as conn:
        # Debit history from May 1 so the history floor doesn't clamp the range.
        _insert(conn, "2026-05-01", "PAYROLL", -2000.0, category="Income")
        _insert(conn, "2026-05-10", "MAY PURCHASE", 10.0)
        _insert(conn, "2026-06-20", "JUNE PURCHASE", 20.0)

    r = build_report(start="2026-05-01", end="2026-06-25")
    trend = {m["month"]: m["partial"] for m in r["monthly_trend"]}
    assert trend["2026-05"] is False   # fully covered
    assert trend["2026-06"] is True    # range ends the 25th

    r = build_report(start="2026-05-02", end="2026-05-31")
    assert r["monthly_trend"][0]["partial"] is True  # starts the 2nd


def test_top_n_per_category():
    with db() as conn:
        for i in range(7):
            _insert(conn, "2026-06-01", f"COFFEE {i}", 1.0 + i)

    r = build_report(range_key="all", top_n=5)
    top = r["top_per_category"]["Food"]
    assert len(top) == 5
    assert top[0]["amount"] == 7.0  # biggest first


def test_account_filter():
    with db() as conn:
        _insert(conn, "2026-06-01", "DEBIT BUY", 10.0, account="Chase Debit")
        _insert(conn, "2026-06-01", "CC BUY", 25.0, account="Chase Credit Card")

    r = build_report(range_key="all", account="Chase Credit Card")
    assert r["totals"]["spend"] == 25.0
