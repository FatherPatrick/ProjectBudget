import pytest

from app.importers import parse_csv_bytes, ParseError

from .fixtures import (
    BOFA_CREDIT_CSV,
    CHASE_CREDIT_CSV,
    CHASE_CREDIT_DUPLICATE_ROWS_CSV,
    CHASE_DEBIT_CSV,
    CHASE_DEBIT_WITH_PREAMBLE_CSV,
)


def test_chase_credit_detected_and_normalized():
    adapter, records = parse_csv_bytes(CHASE_CREDIT_CSV.encode())
    assert adapter.name == "chase_credit"
    assert len(records) == 3
    starbucks = records[0]
    # Raw -5.75 (bank: negative = outflow) flips to +5.75 (spend).
    assert starbucks["amount"] == 5.75
    assert starbucks["txn_date"] == "2026-06-01"
    assert starbucks["raw_category"] == "Food & Drink"
    payment = records[2]
    assert payment["amount"] == -500.00  # money in


def test_chase_debit_detected():
    adapter, records = parse_csv_bytes(CHASE_DEBIT_CSV.encode())
    assert adapter.name == "chase_debit"
    assert len(records) == 3
    assert records[0]["amount"] == -2000.00  # payroll deposit = money in


def test_bofa_credit_detected():
    adapter, records = parse_csv_bytes(BOFA_CREDIT_CSV.encode())
    assert adapter.name == "bofa_credit"
    assert [r["amount"] for r in records] == [15.49, 63.20]


def test_preamble_lines_are_skipped():
    adapter, records = parse_csv_bytes(CHASE_DEBIT_WITH_PREAMBLE_CSV.encode())
    assert adapter.name == "chase_debit"
    assert len(records) == 1
    assert records[0]["description"] == "NW NATURAL BILL PAY"


def test_forced_format_still_skips_preamble():
    adapter, records = parse_csv_bytes(
        CHASE_DEBIT_WITH_PREAMBLE_CSV.encode(), forced="chase_debit"
    )
    assert adapter.name == "chase_debit"
    assert len(records) == 1  # regression: used to bind row 0 as the header → 0 rows


def test_forced_format_unknown_name_is_a_clear_error():
    with pytest.raises(ParseError, match="Unknown format"):
        parse_csv_bytes(CHASE_CREDIT_CSV.encode(), forced="wells_fargo")


def test_forced_format_wrong_file_is_a_clear_error():
    with pytest.raises(ParseError, match="chase_debit"):
        parse_csv_bytes(BOFA_CREDIT_CSV.encode(), forced="chase_debit")


def test_identical_rows_get_distinct_hashes():
    _, records = parse_csv_bytes(CHASE_CREDIT_DUPLICATE_ROWS_CSV.encode())
    assert len(records) == 3
    hashes = {r["hash"] for r in records}
    assert len(hashes) == 3


def test_identical_rows_hash_stably_across_reimports():
    _, first = parse_csv_bytes(CHASE_CREDIT_DUPLICATE_ROWS_CSV.encode())
    _, second = parse_csv_bytes(CHASE_CREDIT_DUPLICATE_ROWS_CSV.encode())
    assert [r["hash"] for r in first] == [r["hash"] for r in second]


def test_empty_file_raises():
    with pytest.raises(ParseError, match="Empty file"):
        parse_csv_bytes(b"")


def test_unrecognized_format_raises():
    with pytest.raises(ParseError, match="Could not detect"):
        parse_csv_bytes(b"a,b,c\n1,2,3\n")
