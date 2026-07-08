from app import categorize as cat
from app.db import db


def test_starter_rules_match_case_insensitively():
    assert cat.categorize("Starbucks Store 123", 5.75) == "Food"
    assert cat.categorize("NETFLIX.COM", 15.49) == "Subscriptions"


def test_whitespace_runs_are_collapsed():
    # Banks pad descriptions with runs of spaces; multi-word patterns must still hit.
    assert cat.categorize("PAYMENT   THANK    YOU-MOBILE", -500) == "Transfer/Payment"


def test_direction_conditional_rules():
    assert cat.categorize("VENMO CASHOUT", -50.0) == "Income"       # money in
    assert cat.categorize("VENMO PAYMENT XYZ", 50.0) != "Income"    # money out


def test_income_patterns_only_match_money_in():
    assert cat.categorize("MOBILE CHECK DEPOSIT", -100.0) == "Income"
    # A spend that merely contains an income-looking word must not be Income.
    assert cat.categorize("SAFE DEPOSIT BOX RENTAL", 25.0) != "Income"
    assert cat.categorize("AMAZON REFUND", -12.99) == "Income"


def test_p2p_money_in_is_income_money_out_is_not():
    # All incoming P2P (reimbursements etc.) counts as income...
    assert cat.categorize("APPLE CASH BANK XFER Patrick Park", -57.30) == "Income"
    assert cat.categorize("VENMO CASHOUT", -50.0) == "Income"
    assert cat.categorize("CASH APP*BRATZ GORL Oakland CA", -40.0) == "Income"
    # ...while outgoing Apple Cash stays a transfer (funding the balance).
    assert cat.categorize("APPLE CASH BANK XFER Patrick Park", 57.30) == "Transfer/Payment"


def test_credit_card_payments_never_count_as_bills():
    # The debit-side descriptors for paying off each card → Transfer/Payment.
    debit_side = [
        "CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224",
        "CHASE CREDIT CRD EPAY 123456",
        "BANK OF AMERICA CREDIT CARD Bill Payment",
        "BA ELECTRONIC PAYMENT",
        "CAPITAL ONE CRCARDPMT 987654",
        "APPLECARD GSBANK PAYMENT",
    ]
    for desc in debit_side:
        assert cat.categorize(desc, 500.0) == "Transfer/Payment", desc
    # ...and the matching money-in on the credit-card side.
    assert cat.categorize("Payment Thank You-Mobile", -500.0) == "Transfer/Payment"
    assert cat.categorize("PAYMENT - THANK YOU", -500.0) == "Transfer/Payment"


def test_bills_cover_loans_utilities_and_waste():
    bills = [
        "ROCKET MTG PMT ID: XXXX",          # mortgage
        "MR COOPER MORT PYMT",              # mortgage (beats generic PYMT tail)
        "MOHELA STUDENT LN PMT",            # student loan
        "NELNET LOAN PAYMENT",              # student loan
        "TOYOTA FINANCIAL SVC LEASE",       # car
        "WASTE MGMT WM EZPAY",              # trash
        "REPUBLIC SERVICES INC",            # trash
        "PORTLAND GENERAL ELEC ONLINE PAY", # power
        "NW NATURAL BILL PAY",              # gas
        "MINT MOBILE PAYMENT",              # phone
    ]
    for desc in bills:
        assert cat.categorize(desc, 100.0) == "Bills", desc


def test_biller_beats_generic_transfer_keywords():
    # Utility paid through bank bill-pay: the biller name must win over the
    # generic "ONLINE PAYMENT"/"AUTOPAY" transfer indicators.
    assert cat.categorize("ONLINE PAYMENT TO PORTLAND GENERAL", 120.0) == "Bills"
    assert cat.categorize("COMCAST XFINITY AUTOPAY", 89.0) == "Bills"


def test_grocery_chains():
    for desc in ["NEW SEASONS MARKET #5", "FRED MEYER #123", "GROCERY OUTLET",
                 "WINCO FOODS", "TRADER JOE'S #42"]:
        assert cat.categorize(desc, 50.0) == "Grocery", desc


def test_real_world_descriptors():
    # Shaped like actual statement lines; regressions found on real data.
    assert cat.categorize("FREEDOM          MTG PYMTS  0162120125", 2100.0) == "Bills"
    assert cat.categorize("NON-CHASE ATM FEE-WITH", 3.0) == "Fees"
    assert cat.categorize("CITY OF GRESHAM UTIL BILLPAY", 95.0) == "Bills"
    # Local merchants whose descriptors end in the city name must NOT be Bills.
    assert cat.categorize("WINCO FOODS #47 2511 S GRESHAM OR", 85.0) == "Grocery"
    assert cat.categorize("WM SUPERCENTER #3178 GRESHAM OR", 60.0) == "Grocery"
    assert cat.categorize("TRADER JOE S #276 GRESHAM OR", 45.0) == "Grocery"
    assert cat.categorize("SPACE AGE FUEL #1 GRESHAM OR", 40.0) == "Transport"
    assert cat.categorize("PY *BLACK ROCK COFFEE BARGRESHAM OR", 6.0) == "Food"
    assert cat.categorize("GOODWILL OF GRESHAM GRESHAM OR", 15.0) == "Shopping"


def test_gresham_portland_locals():
    # Real descriptors from Gresham/Portland-metro statements.
    cases = {
        "SPO*BIGTOWNHERO-GRESHAM": "Food",            # sandwich chain
        "TST* HOPS N DROPS - H 503-482-5016 OR": "Food",
        "DRAGON PALACE INC GRESHAM OR": "Food",
        "KKOKI BBQ PORTLAND OR": "Food",
        "JM BANH MI 131-27305592 IL": "Food",
        "TIN TIN BUFFET PORTLAND OR": "Food",
        "RED ROBIN NO 351 GRESHAM OR": "Food",
        "BUFFALO WILD WNGS 3458": "Food",
        "CHART HOUSE PORTLAND PORTLAND OR": "Food",
        "MARRAKESH MOROCCAN RESTAU": "Food",          # truncated "RESTAURANT"
        "SPACE AGE #1 GRESHAM OR": "Transport",       # OR fuel chain, no "FUEL"
        "MTA*NYCT PAYGO NEW YORK NY": "Transport",
        "FRED-MEYER #0127": "Grocery",                # hyphenated variant
        "H MART BELMONT": "Grocery",
        "OREGON INTERNATIONAL MARK": "Grocery",       # truncated "MARKET"
        "APTIVE ENVIRONMENTAL - PO": "Bills",         # pest control
        "WM.COM 866-909-4458 TX": "Bills",            # Waste Management online
        "PNS*IC SYSTEM INC 800-2797951 MN": "Bills",
        "PNM*JACKSON HEWITT INC SANTA CLARA CA": "Bills",
        "TWILIO INC": "Subscriptions",
        "MT HOOD MEADOWS ONLINE 503-3372222 OR": "Fun",
        "MENS WEARHOUSE #2695 CLACKAMAS OR": "Shopping",
        "Vans Happy Valley Happy Valley OR": "Shopping",
        "POSHMARK 650-488-7740 CA": "Shopping",
        "USPS PO 40094401 28515 BORING OR": "Shopping",
        "ANNUAL MEMBERSHIP FEE": "Fees",
        "APPRAISALFEE-PRMG WWW.REGGORA.C MA": "Fees",
        "COUNTER CHECK": "Fees",
        "APPLE CASH BANK XFER Patrick Park": "Transfer/Payment",
        "MICROSOFT*PC GAME PASS REDMOND WA": "Subscriptions",
        "MICROSOFT*14 DAY TRIAL REDMOND WA": "Subscriptions",
        "DENNY'S #6806 18007336": "Food",
        "MEN105 MENCHIES CLACKA CLACKAMAS OR": "Food",
        "SQ *DON LADIS TACO SHOP": "Food",
        "DD *CAVIAR PHOSEN": "Food",
        "SQ *KMN CATERING Canby OR": "Food",
        "ORIENTAL FOOD VALUE SUPE": "Grocery",
        "KOHL'S #1006 WOOD VILLAGE OR": "Shopping",
        "American Eagle Outfitters": "Shopping",
        "CRAFT WAREHOUSE #13 GRESHAM OR": "Shopping",
        "MINISO GRESHAM TOWN FAIR": "Shopping",
        "OREGON ZOO": "Fun",
        "AXS.COM REN-FEST WITP 888-929-7849 CA": "Fun",
        "ALL STOP PIPES AND TOBACC": "Fun",
        "Wise Inc WISE TrnWise": "Transfer/Payment",
        "SHARETEA GRESHAM clover.com OR": "Food",
        "FRENZI FROZEN YOGURT 503-9121577 OR": "Food",
        "MINUTE MART EXPRESS GRESHAM OR": "Grocery",
        "SALLY BEAUTY 9689": "Shopping",
        "MICROSOFT REDMOND WA": "Subscriptions",
        "OFFICIAL CHECKS CHARGE": "Fees",
        "POINT.ME POINT.ME NY": "Travel",
        "AMERICAN STRATEG 8662748765 8AC92D6EFE67": "Bills",
        "COIN METER LAUNDRY WR PORTLAND OR": "Bills",
        "DAIRY QUEEN #17644": "Food",
        "BRAGANZA TEA": "Food",
        "DOLLARTREE GRESHAM OR": "Shopping",
        "A TO Z PETS INC": "Shopping",
    }
    for desc, expected in cases.items():
        assert cat.categorize(desc, 25.0) == expected, desc


def test_taco_pattern_does_not_match_tacoma():
    assert cat.categorize("PARKING GARAGE TACOMA WA", 12.0) != "Food"


def test_square_vendors_default_to_fun_but_food_wins():
    # Unrecognized Square vendors (fair/event booths) fall through to Fun...
    assert cat.categorize("SQ *WANDERING IN TIME P Canby OR", 26.0) == "Fun"
    assert cat.categorize("SQ *THE KILTED STAG Canby OR", 18.4) == "Fun"
    # ...but a Square merchant matching an earlier group still wins.
    assert cat.categorize("SQ *DON LADIS TACO SHOP", 15.5) == "Food"
    assert cat.categorize("SQ *KMN CATERING Canby OR", 18.0) == "Food"


def test_p2p_out_as_fun_via_learned_direction_rules():
    # Patrick's setup: P2P money out = Fun, money in stays Income.
    cat.add_rule("VENMO", "Fun", direction="out")
    cat.add_rule("CASH APP", "Fun", direction="out")
    assert cat.categorize("VENMO PAYMENT 1037427259727", 45.0) == "Fun"
    assert cat.categorize("CASH APP*BRATZ GORL Oakland CA", 40.0) == "Fun"
    assert cat.categorize("VENMO CASHOUT", -50.0) == "Income"
    assert cat.categorize("CASH APP*PATRICK PARK", -42.0) == "Income"


def test_specific_before_generic_orderings():
    assert cat.categorize("UBER EATS ORDER", 20.0) == "Food"
    assert cat.categorize("UBER TRIP HELP.UBER.COM", 20.0) == "Transport"
    assert cat.categorize("COSTCO GAS #123", 40.0) == "Transport"
    assert cat.categorize("COSTCO WHSE #456", 150.0) == "Grocery"
    assert cat.categorize("DELTA DENTAL OF OREGON", 30.0) == "Health"
    assert cat.categorize("DELTA AIR LINES", 300.0) == "Travel"
    assert cat.categorize("ENTERPRISE RENT-A-CAR", 80.0) == "Travel"


def test_unknown_merchant_falls_back_to_uncategorized():
    assert cat.categorize("TOTALLY UNKNOWN MERCHANT 42", 10.0) == "Uncategorized"


def test_learned_rule_outranks_starter_rule():
    assert cat.categorize("STARBUCKS STORE 123", 5.75) == "Food"
    cat.add_rule("STARBUCKS", "Fun")
    assert cat.categorize("STARBUCKS STORE 123", 5.75) == "Fun"


def test_add_rule_upserts_on_same_pattern():
    cat.add_rule("STARBUCKS", "Fun")
    cat.add_rule("STARBUCKS", "Food")
    rules = cat.list_rules()
    assert len(rules) == 1
    assert rules[0]["category"] == "Food"


def test_delete_rule():
    cat.add_rule("STARBUCKS", "Fun")
    rule_id = cat.list_rules()[0]["id"]
    assert cat.delete_rule(rule_id) is True
    assert cat.delete_rule(rule_id) is False
    assert cat.list_rules() == []


def _insert_txn(conn, desc, amount, category, manually_set=0, hash_key=None):
    conn.execute(
        """INSERT INTO transactions
             (txn_date, description, amount, source_account, category,
              manually_set, hash)
           VALUES ('2026-06-01', ?, ?, 'Chase Debit', ?, ?, ?)""",
        (desc, amount, category, manually_set, hash_key or desc),
    )


def test_reapply_all_respects_manual_pins():
    with db() as conn:
        _insert_txn(conn, "STARBUCKS STORE 123", 5.75, "Travel", manually_set=1,
                    hash_key="pinned")
        _insert_txn(conn, "STARBUCKS STORE 456", 4.25, "Uncategorized",
                    hash_key="unpinned")

    changed = cat.reapply_all()

    with db() as conn:
        rows = {r["hash"]: r["category"] for r in conn.execute(
            "SELECT hash, category FROM transactions").fetchall()}
    assert rows["pinned"] == "Travel"   # untouched despite the Food starter rule
    assert rows["unpinned"] == "Food"   # recomputed
    assert changed == 1
