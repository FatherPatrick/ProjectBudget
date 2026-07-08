from .fixtures import CHASE_CREDIT_CSV, CHASE_DEBIT_CSV


def _upload(client, csv_text, filename="stmt.csv", **form):
    return client.post(
        "/upload",
        files=[("files", (filename, csv_text.encode(), "text/csv"))],
        data=form,
    )


def test_upload_then_reupload_dedupes(client):
    r = _upload(client, CHASE_CREDIT_CSV).json()
    assert r["total_inserted"] == 3
    assert r["files"][0]["detected_account"] == "Chase Credit Card"

    again = _upload(client, CHASE_CREDIT_CSV).json()
    assert again["total_inserted"] == 0
    assert again["total_duplicates_skipped"] == 3


def test_upload_unknown_forced_format_reports_error(client):
    r = _upload(client, CHASE_CREDIT_CSV, format="wells_fargo").json()
    assert "Unknown format" in r["files"][0]["error"]


def test_report_range_alias_and_payload(client):
    _upload(client, CHASE_DEBIT_CSV)
    r = client.get("/report", params={"range": "30d"}).json()
    assert r["range"]["key"] == "30d"
    assert "by_category" in r and "monthly_trend" in r


def test_transactions_limit_is_capped(client):
    assert client.get("/transactions", params={"limit": 0}).status_code == 422
    assert client.get("/transactions", params={"limit": 5000}).status_code == 422


def test_rules_crud(client):
    bad = client.post("/rules", data={"pattern": "X", "category": "Nope"})
    assert bad.status_code == 400

    ok = client.post("/rules", data={"pattern": "STARBUCKS", "category": "Fun"})
    assert ok.status_code == 200

    rules = client.get("/rules").json()
    assert len(rules) == 1 and rules[0]["pattern"] == "STARBUCKS"

    rule_id = rules[0]["id"]
    assert client.delete(f"/rules/{rule_id}").status_code == 200
    assert client.delete(f"/rules/{rule_id}").status_code == 404
    assert client.get("/rules").json() == []


def test_custom_category_roundtrip(client):
    assert client.post("/categories", data={"name": "Pets"}).status_code == 200
    assert client.post("/categories", data={"name": "Pets"}).status_code == 409
    names = [c["name"] for c in client.get("/categories").json()]
    assert "Pets" in names
    # New category is immediately usable in a rule.
    r = client.post("/rules", data={"pattern": "CHEWY", "category": "Pets"})
    assert r.status_code == 200


def test_manual_pin_survives_rule_reapply(client):
    _upload(client, CHASE_CREDIT_CSV)
    txns = client.get("/transactions").json()
    starbucks = next(t for t in txns if "STARBUCKS" in t["description"])

    pin = client.post(f"/transactions/{starbucks['id']}/category",
                      data={"category": "Travel"})
    assert pin.status_code == 200

    # Teaching an overlapping rule must not clobber the pinned transaction.
    client.post("/rules", data={"pattern": "STARBUCKS", "category": "Fun"})
    after = client.get("/transactions").json()
    pinned = next(t for t in after if t["id"] == starbucks["id"])
    assert pinned["category"] == "Travel"


def test_export_csv(client):
    _upload(client, CHASE_CREDIT_CSV)
    r = client.get("/export/transactions.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("date,description,amount")
    assert len(lines) == 4  # header + 3 transactions


def test_reset_requires_confirmation(client):
    _upload(client, CHASE_CREDIT_CSV)
    assert client.post("/reset", data={"confirm": "yes"}).status_code == 400

    r = client.post("/reset", data={"confirm": "DELETE"}).json()
    assert r["transactions_deleted"] == 3
    assert client.get("/transactions").json() == []
